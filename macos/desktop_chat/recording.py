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


class RecordingButton(tk.Button):
    def __init__(self, master, send, report, **kwargs):
        super().__init__(master, text="", relief="flat", **kwargs)
        self.send, self.report = send, report
        self.video = False
        self.job = None
        self.process = None
        self.started = None
        self.path = None
        self.icons = {}
        try:
            from AppKit import NSImage
            from PIL import Image, ImageTk
            for symbol in ("mic.fill", "video.fill"):
                native = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, None)
                image = Image.open(io.BytesIO(bytes(native.TIFFRepresentation()))).convert("RGBA")
                image.thumbnail((24, 24), Image.Resampling.LANCZOS)
                self.icons[symbol] = ImageTk.PhotoImage(image)
        except Exception:
            pass
        self.show_mode()
        self.results = queue.Queue()
        self.after(100, self.poll)
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<ButtonRelease-1>", self.release)
        self.bind("<Escape>", self.cancel)
        self.bind("<Destroy>", lambda event: self.cancel() if event.widget is self else None)

    def show_mode(self):
        image = self.icons.get("video.fill" if self.video else "mic.fill")
        self.configure(image=image or "", text="" if image else ("Видео" if self.video else "Голос"))

    def poll(self):
        try:
            while True:
                path = self.results.get_nowait()
                if path: self.send(path)
                else: self.report("Запись не получилась. Проверьте разрешения микрофона и камеры в настройках macOS.")
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def press(self, _event):
        self.focus_set()
        self.job = self.after(250, self.start)

    def start(self):
        self.job = None
        executable = shutil.which("ffmpeg") or ("/opt/homebrew/bin/ffmpeg" if os.path.isfile("/opt/homebrew/bin/ffmpeg") else None)
        if not executable:
            self.report("Для записи необходим ffmpeg. Установите его и перезапустите приложение.")
            return
        self.path = os.path.join(tempfile.gettempdir(), "oc-%s-%s.%s" % ("circle" if self.video else "voice", uuid.uuid4(), "mp4" if self.video else "m4a"))
        arguments = [executable, "-y", "-f", "avfoundation"]
        if self.video: arguments += ["-framerate", "30"]
        arguments += ["-i", "0:0" if self.video else ":0", "-t", "60"]
        if self.video:
            arguments += ["-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=320:320", "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "350k", "-pix_fmt", "yuv420p"]
        arguments += ["-c:a", "aac", "-b:a", "48k", self.path]
        self.process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.started = time.monotonic()
        self.configure(image="", text="● Отпустите", fg="#E25B5B")
        process = self.process
        self.after(61000, lambda: self.finish() if self.process is process else None)

    def release(self, _event):
        if self.job:
            self.after_cancel(self.job)
            self.job = None
            self.video = not self.video
            self.show_mode()
        else:
            self.finish()

    def cancel(self, _event=None):
        self.finish(cancel=True)

    def finish(self, cancel=False):
        if not self.process:
            return
        process, path = self.process, self.path
        self.process = None
        duration = time.monotonic() - self.started
        if self.winfo_exists():
            self.show_mode()
        def finalize():
            try:
                process.communicate(input=b"q\n", timeout=8)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
            valid = not cancel and duration >= 0.5 and os.path.isfile(path) and os.path.getsize(path) > 1000
            if valid:
                self.results.put(path)
            else:
                if os.path.isfile(path): os.unlink(path)
                if not cancel: self.results.put(None)
        threading.Thread(target=finalize, daemon=True).start()
