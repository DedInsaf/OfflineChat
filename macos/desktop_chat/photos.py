"""Photo previews keep their proportions and fit the transcript viewport."""
import tkinter as tk
from PIL import Image, ImageOps, ImageTk
from .media_workers import thumbnail_workers


def read_thumbnail(path):
    with Image.open(path) as opened:
        opened.draft("RGB", (720, 520))
        image = ImageOps.exif_transpose(opened)
        image.thumbnail((360, 260), Image.Resampling.LANCZOS)
        return image.copy()


class PhotoPreview(tk.Label):
    def __init__(self, master, path, viewport, **kwargs):
        super().__init__(master, borderwidth=0, highlightthickness=0, **kwargs)
        self.source = None
        self.closed = False
        self.load_job = None
        self.future = thumbnail_workers.submit(read_thumbnail, path)
        color = tuple(channel // 257 for channel in self.winfo_rgb(self.cget("bg")))
        self.image = ImageTk.PhotoImage(Image.new("RGB", (240, 160), color))
        self.configure(image=self.image)
        self.viewport = viewport
        self.last_size = None
        self.resize_job = None
        self.binding = viewport.bind("<Configure>", self.schedule_resize, add="+")
        self.bind("<Destroy>", self.cleanup, add="+")
        self.check_loaded()

    def check_loaded(self):
        self.load_job = None
        if self.closed: return
        if not self.future.done():
            self.load_job = self.after(30, self.check_loaded)
            return
        try: self.source = self.future.result()
        except (OSError, ValueError):
            self.configure(image="", text="Не удалось показать фото")
            return
        self.render()

    def schedule_resize(self, _event):
        if self.resize_job: self.after_cancel(self.resize_job)
        self.resize_job = self.after(100, self.render)

    def render(self):
        self.resize_job = None
        if self.source is None or self.closed: return
        width = self.viewport.winfo_width()
        limit = max(40, width - 84) if width > 1 else 360
        image = self.source.copy()
        image.thumbnail((min(360, limit), 260), Image.Resampling.LANCZOS)
        if image.size == self.last_size: return
        self.last_size = image.size
        self.image = ImageTk.PhotoImage(image)
        self.configure(image=self.image)

    def cleanup(self, event):
        if event.widget is not self: return
        self.closed = True
        self.future.cancel()
        if self.load_job: self.after_cancel(self.load_job)
        if self.resize_job: self.after_cancel(self.resize_job)
        self.viewport.unbind("<Configure>", self.binding)
