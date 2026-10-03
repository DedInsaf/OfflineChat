"""Photo previews keep their proportions and fit the transcript viewport."""
import tkinter as tk
from PIL import Image, ImageOps, ImageTk


class PhotoPreview(tk.Label):
    def __init__(self, master, path, viewport, **kwargs):
        super().__init__(master, borderwidth=0, highlightthickness=0, **kwargs)
        with Image.open(path) as opened:
            self.source = ImageOps.exif_transpose(opened)
        self.source.thumbnail((360, 260), Image.Resampling.LANCZOS)
        self.viewport = viewport
        self.last_size = None
        self.resize_job = None
        self.binding = viewport.bind("<Configure>", self.schedule_resize, add="+")
        self.bind("<Destroy>", self.cleanup, add="+")
        self.render()

    def schedule_resize(self, _event):
        if self.resize_job: self.after_cancel(self.resize_job)
        self.resize_job = self.after(100, self.render)

    def render(self):
        self.resize_job = None
        width = self.viewport.winfo_width()
        limit = max(40, width - 52) if width > 1 else 360
        image = self.source.copy()
        image.thumbnail((min(360, limit), 260), Image.Resampling.LANCZOS)
        if image.size == self.last_size: return
        self.last_size = image.size
        self.image = ImageTk.PhotoImage(image)
        self.configure(image=self.image)

    def cleanup(self, event):
        if event.widget is not self: return
        if self.resize_job: self.after_cancel(self.resize_job)
        self.viewport.unbind("<Configure>", self.binding)
