"""Bounded live capture feed. Worker threads never touch Tk widgets."""
import math
import queue
import threading
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk
from .shared import THEME

SIDE = 176


def capture_arguments(executable, path, video, duration=60):
    args = [executable, "-y", "-nostats", "-thread_queue_size", "4", "-f", "avfoundation"]
    if video: args += ["-framerate", "30"]
    args += ["-i", "0:0" if video else ":0", "-t", str(duration)]
    if video:
        args += ["-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=320:320",
                 "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "350k", "-pix_fmt", "yuv420p"]
    args += ["-af", "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
             "-c:a", "aac", "-b:a", "48k", path]
    if video:
        # A second output from the SAME camera input, not a second camera session.
        args += ["-map", "0:v:0", "-an", "-t", str(duration), "-vf",
                 f"fps=30,crop=min(iw\\,ih):min(iw\\,ih),scale={SIDE}:{SIDE}",
                 "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    return args


class CaptureFeed:
    def __init__(self, process, video):
        self.frames = queue.Queue(maxsize=1)
        self.level = 0.0
        self.ready = False
        self.closed = False
        threading.Thread(target=self.read_levels, args=(process.stderr,), daemon=True).start()
        if video:
            threading.Thread(target=self.read_frames, args=(process.stdout,), daemon=True).start()

    def read_levels(self, stream):
        try:
            for raw in iter(stream.readline, b""):
                if self.closed: continue  # Drain until EOF so ffmpeg cannot block.
                line = raw.decode("utf-8", errors="replace")
                if "lavfi.astats.Overall.RMS_level=" in line:
                    try:
                        db = float(line.rsplit("=", 1)[-1])
                        self.level = max(0.0, min(1.0, (db + 60) / 60)) if math.isfinite(db) else 0.0
                        self.ready = True
                    except ValueError: pass
        finally:
            stream.close()

    def read_frames(self, stream):
        size = SIDE * SIDE * 3
        try:
            while True:
                data = bytearray()
                while len(data) < size:
                    chunk = stream.read(size - len(data))
                    if not chunk: return
                    data.extend(chunk)
                if self.closed: continue
                frame = Image.frombytes("RGB", (SIDE, SIDE), bytes(data))
                self.ready = True
                try: self.frames.get_nowait()
                except queue.Empty: pass
                try: self.frames.put_nowait(frame)
                except queue.Full: pass
        finally:
            stream.close()


class CapturePreview(tk.Canvas):
    def __init__(self, master, feed, video):
        super().__init__(master, width=SIDE if video else 300, height=SIDE if video else 58,
                         bg=THEME.get("surface", "#171A1F"), highlightthickness=0, bd=0)
        self.feed, self.video = feed, video
        self.accent = THEME.get("accent", "#3EE0B4")
        self.text_color = THEME.get("text", "#E8EEF4")
        self.placeholder_color = THEME.get("surface_alt", "#232831")
        self.mask = Image.new("L", (SIDE * 4, SIDE * 4))
        ImageDraw.Draw(self.mask).ellipse((4, 4, SIDE * 4 - 5, SIDE * 4 - 5), fill=255)
        self.mask = self.mask.resize((SIDE, SIDE), Image.Resampling.LANCZOS)
        self.closed = False
        self.levels = [0.0] * 42
        self.photo = None
        self.image_item = None
        self.waiting_drawn = False
        self.job = None
        self.wave_items = []
        if not video:
            self.wave_items = [self.create_line(8 + i * 7, 28, 8 + i * 7, 30,
                                                fill=self.accent, width=3, capstyle="round") for i in range(42)]
        self.bind("<Destroy>", self.cleanup)
        self.tick()

    def tick(self):
        if self.closed: return
        if self.video:
            try:
                frame = self.feed.frames.get_nowait().convert("RGBA")
                frame.putalpha(self.mask)
                if self.photo is None:
                    self.photo = ImageTk.PhotoImage(frame)
                    self.delete("all")
                    self.image_item = self.create_image(SIDE / 2, SIDE / 2, image=self.photo)
                else:
                    self.photo.paste(frame)
            except queue.Empty:
                if self.photo is None and not self.waiting_drawn:
                    self.waiting_drawn = True
                    self.delete("all")
                    self.create_oval(1, 1, SIDE - 1, SIDE - 1, fill=self.placeholder_color, outline="")
                    self.create_text(SIDE / 2, SIDE / 2, text="Подключение\nкамеры…",
                                     fill=self.text_color, justify="center")
        else:
            self.levels = self.levels[1:] + [self.feed.level]
            for i, level in enumerate(self.levels):
                height = max(3, level * 42)
                self.coords(self.wave_items[i], 8 + i * 7, 29 - height / 2, 8 + i * 7, 29 + height / 2)
        # A paused preview needs no redraw loop. It retains its last camera frame.
        if not getattr(self.feed, "closed", False):
            self.job = self.after(16 if self.video else 85, self.tick)

    def cleanup(self, event):
        if event.widget is not self: return
        self.closed = True
        if self.job: self.after_cancel(self.job)
