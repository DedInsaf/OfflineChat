"""Hold/lock/cancel recording control. Worker threads never access Tk widgets."""
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import tkinter as tk
from .shared import THEME, ui_font
from .capture_preview import CaptureFeed, CapturePreview, capture_arguments
from .recording_segments import join_segments
from .recording_ui import RecordingHints, RecordingAction, symbol_photo


class RecordingButton(tk.Canvas):
    def __init__(self, master, send, report, status_host=None, on_state=None, **kwargs):
        self.idle_fg = kwargs.pop("fg", THEME.get("accent", "#3EE0B4"))
        kwargs.pop("font", None)
        super().__init__(master, width=44, height=44, highlightthickness=0, bd=0, cursor="hand2", takefocus=True, **kwargs)
        self.send, self.report = send, report
        self.on_state = on_state or (lambda active: None)
        self.video = False
        self.job = self.process = self.started = self.path = None
        self.locked = self.cancelled = self.paused = self.finalizing = False
        self.origin = (0, 0)
        self.draft = self.actions = self.preview = None
        self.status_host = status_host or master
        self.panel = self.status_label = self.hints = self.timer_job = None
        self.feed = self.live_preview = None
        self.generation = 0
        self.elapsed = 0
        self.segments = []
        self.destroyed = False
        self.worker_generation = None
        self.poll_job = None
        self.icons = {name: symbol_photo(name, THEME["primary_fg"]) for name in ("mic.fill", "video.fill", "arrow.up")}
        self.results = queue.Queue()
        self.show_mode()
        self.poll_job = self.after(80, self.poll)
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<ButtonRelease-1>", self.release)
        self.bind("<B1-Motion>", self.drag)
        self.bind("<Escape>", self.cancel)
        self.bind("<Destroy>", self.destroy_recording)

    def show_mode(self):
        self.delete("all")
        active = self.process is not None and not self.locked
        self.create_oval(0 if active else 3, 0 if active else 3, 44 if active else 41, 44 if active else 41,
                         fill=THEME["primary"], outline="")
        sending = self.draft or (self.locked and not self.paused)
        image = self.icons.get("arrow.up" if sending else ("video.fill" if self.video else "mic.fill"))
        if image: self.create_image(22, 22, image=image)
        else: self.create_text(22, 22, text="↑" if sending else ("Видео" if self.video else "Голос"), fill=THEME["primary_fg"], font=ui_font(9))

    @staticmethod
    def remove_paths(paths, keep=None):
        for path in set(paths):
            if path and path != keep:
                try: os.unlink(path)
                except FileNotFoundError: pass

    def poll(self):
        self.poll_job = None
        try:
            while True:
                kind, paths, path, error, generation = self.results.get_nowait()
                if generation == self.worker_generation:
                    self.finalizing = False
                    self.worker_generation = None
                if generation != self.generation or self.destroyed:
                    self.remove_paths(paths + ([path] if path else []))
                    continue
                if kind == "paused" or (kind == "error" and paths):
                    self.segments = paths
                    self.paused = self.locked = True
                    self.show_actions()
                else:
                    self.remove_paths(paths, keep=path)
                    self.segments = []
                    self.clear_actions()
                    if kind == "review" and path:
                        self.draft = path
                        self.show_actions(review=True)
                    elif kind == "send" and path: self.send(path)
                if error: self.report(error)
                self.show_mode()
        except queue.Empty:
            pass
        if not self.destroyed: self.poll_job = self.after(80, self.poll)

    def press(self, event):
        if self.finalizing: return
        if self.draft:
            self.send_draft()
            self.cancelled = True
            return
        if self.locked:
            self.cancelled = True
            if self.paused: self.start(resuming=True)
            else: self.finish()
            return
        self.cancelled = False
        self.origin = (event.x_root, event.y_root)
        self.focus_set()
        self.job = self.after(250, self.start)

    def drag(self, event):
        if self.locked or self.cancelled: return
        dx, dy = event.x_root - self.origin[0], event.y_root - self.origin[1]
        if getattr(self, "hints", None):
            self.hints.update_drag(dx, dy, lock_x=self.lock_position())
        if dx <= -96:
            self.cancelled = True
            self.cancel()
        elif dy <= -80:
            self.locked = True
            # Locking before the hold delay must also start the capture.
            if self.job:
                self.after_cancel(self.job)
                self.job = None
                self.start()
            self.show_actions()
            self.show_mode()

    def lock_position(self):
        return self.winfo_rootx() + 22 - self.hints.winfo_rootx() if self.hints else None

    def show_actions(self, review=False):
        self.show_status("Готово к отправке" if review else None)
        if self.actions: self.actions.destroy()
        self.actions = tk.Frame(self.panel, bg=THEME["surface"])
        self.actions.pack(fill="x", padx=12, pady=(0, 8))
        RecordingAction(self.actions, "trash", "Удалить", self.cancel).pack(side="left")
        if review:
            from .playback import RecordedMessage
            if self.preview: self.preview.destroy()
            self.preview = RecordedMessage(self.panel, self.draft, circle=self.video)
            self.preview.configure(bg=THEME["surface"])
            self.preview.pack(anchor="center" if self.video else "w", padx=12, pady=6, before=self.actions)
        else:
            RecordingAction(self.actions, "play.fill" if self.paused else "pause.fill",
                            "Просмотр" if self.paused else "Пауза",
                            (lambda: self.finish(review=True)) if self.paused else self.pause).pack(side="right", padx=8)
            if self.paused:
                RecordingAction(self.actions, "video.fill" if self.video else "mic.fill", "Продолжить",
                                lambda: self.start(resuming=True)).pack(side="right", padx=8)

    def send_draft(self):
        if self.finalizing: return
        path, self.draft = self.draft, None
        self.clear_actions()
        self.show_mode()
        if path: self.send(path)

    def clear_actions(self):
        if self.actions: self.actions.destroy(); self.actions = None
        if self.preview: self.preview.destroy(); self.preview = None
        self.locked = self.paused = False
        self.hide_status()
        if not self.destroyed: self.on_state(False)

    def show_status(self, text=None):
        if self.timer_job: self.after_cancel(self.timer_job); self.timer_job = None
        if self.panel is None:
            self.panel = tk.Frame(self.status_host, bg=THEME["surface"])
            siblings = [child for child in self.status_host.winfo_children() if child is not self.panel and child.winfo_manager() == "pack"]
            self.panel.pack(fill="x", before=siblings[0] if siblings else None)
            self.hints = RecordingHints(self.panel, self.cancel)
            self.hints.pack(fill="x")
            self.hints.bind("<Configure>", lambda _: self.update_hint_position(), add="+")
            self.status_label = tk.Label(self.hints, bg=THEME["surface"], fg=THEME["text"], font=ui_font(15), anchor="w")
        if self.process and self.feed and self.live_preview is None:
            self.live_preview = CapturePreview(self.panel, self.feed, self.video)
            self.live_preview.pack(anchor="center" if self.video else "w", padx=12, pady=(8, 8), before=self.hints)
        self.hints.message = bool(text)
        self.hints.update_drag(locked=self.locked or self.paused or bool(text), lock_x=self.lock_position())
        self.status_label.place(x=12 if text else 28, y=22 if self.locked or self.paused or text else 74, anchor="w")
        if text:
            # Processing/draft captions do not advertise cancellation gestures.
            self.hints.delete("all")
            self.status_label.configure(text=text)
        else: self.update_status()
        self.on_state(True)

    def update_hint_position(self):
        if self.hints:
            self.hints.update_drag(self.hints.dx, self.hints.dy, self.hints.locked, self.lock_position())

    def update_status(self):
        self.timer_job = None
        if not self.panel: return
        if self.process and self.process.poll() is not None:
            self.finish(review=self.locked)
            return
        seconds = min(60, int(self.elapsed + (time.monotonic() - self.started if self.process else 0)))
        state = "Пауза  " if self.paused else ("Запуск…  " if self.feed and not self.feed.ready else "")
        self.hints.indicator_color = THEME["muted"] if self.paused else THEME["danger"]
        self.update_hint_position()
        self.status_label.configure(text=f"{state}{seconds // 60:02d}:{seconds % 60:02d}")
        if self.process:
            if seconds >= 60:
                self.finish(review=self.locked)
                return
            self.timer_job = self.after(200, self.update_status)

    def hide_status(self):
        if self.timer_job: self.after_cancel(self.timer_job); self.timer_job = None
        if self.panel: self.panel.destroy()
        self.panel = self.status_label = self.hints = self.live_preview = None
        self.actions = self.preview = None

    def start(self, resuming=False):
        self.job = None
        if self.finalizing or self.destroyed or self.process: return
        from .playback import RecordedMessage
        active = RecordedMessage.active() if RecordedMessage.active else None
        if active is not None and active.playing: active.toggle()
        self.executable = shutil.which("ffmpeg") or ("/opt/homebrew/bin/ffmpeg" if os.path.isfile("/opt/homebrew/bin/ffmpeg") else None)
        if not self.executable:
            self.locked = False
            self.report("Для записи необходим ffmpeg. Установите его и перезапустите приложение.")
            return
        if not resuming:
            self.generation += 1
            self.elapsed = 0
            self.segments = []
        if self.elapsed >= 60: self.finish(review=True); return
        self.hide_status()
        self.paused = False
        self.path = os.path.join(tempfile.gettempdir(), f"oc-{'circle' if self.video else 'voice'}-{uuid.uuid4()}.{'mp4' if self.video else 'm4a'}")
        try:
            self.process = subprocess.Popen(capture_arguments(self.executable, self.path, self.video, max(0.1, 60 - self.elapsed)),
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE if self.video else subprocess.DEVNULL, stderr=subprocess.PIPE)
        except OSError as error:
            self.paused = self.locked = bool(self.segments)
            self.report("Не удалось начать запись: %s" % error)
            if self.segments: self.show_actions()
            return
        self.started = time.monotonic()
        self.feed = CaptureFeed(self.process, self.video)
        self.show_mode()
        if self.locked: self.show_actions()
        else: self.show_status()

    def release(self, _event):
        if self.cancelled: self.cancelled = False; return
        if self.locked: return
        if self.job:
            self.after_cancel(self.job); self.job = None
            self.video = not self.video
            self.show_mode()
        else: self.finish()

    def pause(self):
        if self.process and not self.finalizing: self.finish(pause=True)

    def cancel(self, _event=None):
        self.generation += 1
        if self.job: self.after_cancel(self.job); self.job = None
        self.remove_paths(self.segments + ([self.draft] if self.draft else []))
        self.segments = []
        self.draft = None
        self.clear_actions()
        if self.process: self.finish(cancel=True)
        if not self.destroyed: self.show_mode()

    def destroy_recording(self, event):
        if event.widget is not self: return
        self.destroyed = True
        if self.poll_job: self.after_cancel(self.poll_job); self.poll_job = None
        self.cancel()

    def finish(self, cancel=False, review=False, pause=False):
        if self.finalizing: return
        process, path, generation = self.process, self.path, self.generation
        if not process and not self.segments: return
        paths = list(self.segments)
        segment_duration = time.monotonic() - self.started if process else 0
        self.elapsed = min(60, self.elapsed + segment_duration)
        self.process = None
        self.finalizing = True
        self.worker_generation = generation
        if self.feed: self.feed.closed = True
        if self.timer_job: self.after_cancel(self.timer_job); self.timer_job = None
        if not cancel and not self.destroyed:
            self.show_status("Пауза…" if pause else "Сохраняем запись…")
        elif not self.destroyed: self.show_mode()
        def finalize():
            result = None
            try:
                if process:
                    try:
                        process.stdin.write(b"q\n"); process.stdin.flush()
                    except (BrokenPipeError, OSError): pass
                    finally: process.stdin.close()
                    try: process.wait(timeout=8)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                    if os.path.isfile(path) and os.path.getsize(path) > 1000 and segment_duration >= 0.15:
                        paths.append(path)
                    else:
                        self.remove_paths([path])
                        if not paths and segment_duration >= 0.5 and not cancel:
                            raise RuntimeError("Запись не получилась. Проверьте разрешения микрофона и камеры в настройках macOS.")
                if cancel or generation != self.generation or self.destroyed:
                    self.remove_paths(paths)
                    kind = "cancelled"
                    paths.clear()
                elif pause:
                    kind = "paused" if paths else "empty"
                elif paths and self.elapsed >= 0.5:
                    result = join_segments(self.executable, paths, self.video)
                    kind = "review" if review else "send"
                else: kind = "empty"
                if generation != self.generation or self.destroyed:
                    self.remove_paths(paths + ([result] if result else []))
                    result = None
                self.results.put((kind, paths, result, None, generation))
            except Exception as error:
                if self.destroyed or generation != self.generation:
                    self.remove_paths(paths + ([result] if result else []))
                    self.results.put(("cancelled", [], None, None, generation))
                else: self.results.put(("error", paths, None, str(error), generation))
        threading.Thread(target=finalize, daemon=True).start()
