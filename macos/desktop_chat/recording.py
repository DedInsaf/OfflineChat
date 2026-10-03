"""Hold-to-record control; capture runs outside Tk's event loop."""
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import queue
import tkinter as tk
import io
from .shared import THEME, PillButton, hex_to_rgb
from .capture_preview import CaptureFeed, CapturePreview, capture_arguments


class RecordingButton(tk.Canvas):
    def __init__(self, master, send, report, status_host=None, **kwargs):
        self.idle_fg = kwargs.pop("fg", THEME.get("accent", "#3EE0B4"))
        kwargs.pop("font", None)
        super().__init__(master, width=40, height=40, highlightthickness=0, bd=0,
                         cursor="hand2", **kwargs)
        self.send, self.report = send, report
        self.video = False
        self.job = None
        self.process = None
        self.started = None
        self.path = None
        self.locked = False
        self.cancelled = False
        self.origin = (0, 0)
        self.draft = None
        self.actions = None
        self.preview = None
        self.status_host = status_host or master
        self.panel = None
        self.status_label = None
        self.timer_job = None
        self.feed = None
        self.live_preview = None
        self.generation = 0
        self.finalizing = False
        self.icons = {}
        try:
            from AppKit import NSImage
            from PIL import Image, ImageTk
            for symbol in ("mic.fill", "video.fill"):
                native = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, None)
                image = Image.open(io.BytesIO(bytes(native.TIFFRepresentation()))).convert("RGBA")
                image = image.resize((22, 22), Image.Resampling.LANCZOS)
                tinted = Image.new("RGBA", image.size, (*hex_to_rgb(self.idle_fg), 0))
                tinted.putalpha(image.getchannel("A"))
                self.icons[symbol] = ImageTk.PhotoImage(tinted)
        except Exception:
            pass
        self.show_mode()
        self.results = queue.Queue()
        self.after(100, self.poll)
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<ButtonRelease-1>", self.release)
        self.bind("<B1-Motion>", self.drag)
        self.bind("<Escape>", self.cancel)
        self.bind("<Destroy>", lambda event: self.cancel() if event.widget is self else None)

    def show_mode(self):
        image = self.icons.get("video.fill" if self.video else "mic.fill")
        self.delete("all")
        if image: self.create_image(20, 20, image=image)
        else: self.create_text(20, 20, text="Видео" if self.video else "Голос", fill=self.idle_fg)
        if self.process:
            self.create_oval(30, 3, 37, 10, fill=THEME.get("danger", "#E25B5B"), outline="")

    def poll(self):
        try:
            while True:
                path, review, generation = self.results.get_nowait()
                if generation != self.generation:
                    if path and os.path.isfile(path): os.unlink(path)
                    continue
                self.show_mode()
                self.hide_status()
                if path and review:
                    self.draft = path
                    self.show_actions(review=True)
                elif path: self.send(path)
                else: self.report("Запись не получилась. Проверьте разрешения микрофона и камеры в настройках macOS.")
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def press(self, _event):
        if self.locked or self.draft or self.finalizing: return
        self.cancelled = False
        self.origin = (_event.x_root, _event.y_root)
        self.focus_set()
        self.job = self.after(250, self.start)

    def drag(self, event):
        dx, dy = event.x_root - self.origin[0], event.y_root - self.origin[1]
        if dx < -80 and not self.locked:
            self.cancelled = True
            self.cancel()
        elif dy < -65 and not self.cancelled:
            self.locked = True
            self.show_actions()

    def show_actions(self, review=False):
        self.show_status("Запись готова" if review else None)
        if self.actions: self.actions.destroy()
        self.actions = tk.Frame(self.panel, bg=self.cget("bg"))
        self.actions.pack(fill="x", padx=12, pady=(0, 8))
        def action(label, command, primary=False):
            PillButton(self.actions, label, command=command, variant="primary" if primary else "secondary",
                       width=110, height=34).pack(side="left", padx=(0, 6), pady=2)
        action("Удалить" if review else "Отмена", self.cancel)
        if review:
            from .playback import RecordedMessage
            if self.preview: self.preview.destroy()
            self.preview = RecordedMessage(self.panel, self.draft, circle=self.video)
            self.preview.pack(anchor="w", padx=12, pady=6, before=self.actions)
            action("Отправить", self.send_draft, True)
        else:
            action("Просмотреть" if self.video else "Прослушать", lambda: self.finish(review=True))
            action("Отправить", self.finish, True)

    def send_draft(self):
        path, self.draft = self.draft, None
        self.clear_actions()
        self.send(path)

    def clear_actions(self):
        if self.actions: self.actions.destroy(); self.actions = None
        if self.preview: self.preview.destroy(); self.preview = None
        self.locked = False
        self.hide_status()

    def show_status(self, text=None):
        if self.timer_job:
            self.after_cancel(self.timer_job)
            self.timer_job = None
        if self.panel is None:
            self.panel = tk.Frame(self.status_host, bg=THEME.get("surface", self.cget("bg")))
            children = self.status_host.winfo_children()
            siblings = [child for child in children if child is not self.panel and child.winfo_manager() == "pack"]
            self.panel.pack(fill="x", before=siblings[0] if siblings else None)
            self.status_label = tk.Label(self.panel, bg=self.panel.cget("bg"), fg=THEME.get("text", "#E8EEF4"),
                                         anchor="w", justify="left", wraplength=380,
                                         font=("Helvetica", 13, "bold"))
            self.status_label.pack(fill="x", padx=12, pady=8)
        if self.process and self.feed and self.live_preview is None:
            self.live_preview = CapturePreview(self.panel, self.feed, self.video)
            self.live_preview.pack(anchor="center" if self.video else "w", padx=12, pady=(0, 8))
        if text:
            self.status_label.configure(text=text)
        else:
            self.update_status()

    def update_status(self):
        self.timer_job = None
        if not self.panel or not self.process: return
        if self.process.poll() is not None:
            self.finish()
            return
        seconds = int(time.monotonic() - self.started)
        mode = "Видеокружок" if self.video else "Голосовое"
        hint = "Запись закреплена" if self.locked else "↑ Закрепить   ·   ← Отменить"
        state = "Подключение…" if self.feed and not self.feed.ready else "● Запись"
        self.status_label.configure(text=f"{state} · {mode}  {seconds // 60:02d}:{seconds % 60:02d}\n{hint}")
        self.timer_job = self.after(250, self.update_status)

    def hide_status(self):
        if self.timer_job:
            self.after_cancel(self.timer_job)
            self.timer_job = None
        if self.panel: self.panel.destroy()
        self.panel = self.status_label = None
        self.live_preview = None

    def start(self):
        self.generation += 1
        from .playback import RecordedMessage
        active = RecordedMessage.active() if RecordedMessage.active else None
        if active is not None and active.playing: active.toggle()
        self.job = None
        executable = shutil.which("ffmpeg") or ("/opt/homebrew/bin/ffmpeg" if os.path.isfile("/opt/homebrew/bin/ffmpeg") else None)
        if not executable:
            self.report("Для записи необходим ffmpeg. Установите его и перезапустите приложение.")
            return
        self.path = os.path.join(tempfile.gettempdir(), "oc-%s-%s.%s" % ("circle" if self.video else "voice", uuid.uuid4(), "mp4" if self.video else "m4a"))
        arguments = capture_arguments(executable, self.path, self.video)
        try:
            self.process = subprocess.Popen(arguments, stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE if self.video else subprocess.DEVNULL,
                                            stderr=subprocess.PIPE)
        except OSError as error:
            self.report("Не удалось начать запись: %s" % error)
            return
        self.started = time.monotonic()
        self.feed = CaptureFeed(self.process, self.video)
        self.show_mode()
        self.show_status()
        process = self.process
        self.after(61000, lambda: self.finish() if self.process is process else None)

    def release(self, _event):
        if self.cancelled: self.cancelled = False; return
        if self.locked: return
        if self.job:
            self.after_cancel(self.job)
            self.job = None
            self.video = not self.video
            self.show_mode()
        else:
            self.finish()

    def cancel(self, _event=None):
        self.generation += 1
        if self.job: self.after_cancel(self.job); self.job = None
        if self.draft and os.path.isfile(self.draft): os.unlink(self.draft)
        self.draft = None
        self.clear_actions()
        self.finish(cancel=True)

    def finish(self, cancel=False, review=False):
        if not self.process:
            return
        process, path = self.process, self.path
        generation = self.generation
        self.process = None
        self.finalizing = True
        if self.feed: self.feed.closed = True
        self.clear_actions()
        duration = time.monotonic() - self.started
        if self.winfo_exists():
            self.show_mode()
            if not cancel: self.show_status("Обработка записи…")
        def finalize():
            try:
                try:
                    process.stdin.write(b"q\n")
                    process.stdin.flush()
                except (BrokenPipeError, OSError): pass
                finally: process.stdin.close()
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
            valid = not cancel and duration >= 0.5 and os.path.isfile(path) and os.path.getsize(path) > 1000
            valid = valid and generation == self.generation
            self.finalizing = False
            if valid:
                self.results.put((path, review, generation))
            else:
                if os.path.isfile(path): os.unlink(path)
                if not cancel and generation == self.generation: self.results.put((None, False, generation))
        threading.Thread(target=finalize, daemon=True).start()
