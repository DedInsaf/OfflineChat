"""Small, themed recording hints. Animations are finite and never rebuild a chat."""
import io
import time
import tkinter as tk
from PIL import Image, ImageTk
from .shared import THEME, hex_to_rgb, mix_hex, ui_font

_symbols = {}


def symbol_photo(name, color, size=22):
    key = (name, color, size)
    if key not in _symbols:
        try:
            from AppKit import NSImage
            native = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
            image = Image.open(io.BytesIO(bytes(native.TIFFRepresentation()))).convert("RGBA")
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            tinted = Image.new("RGBA", image.size, (*hex_to_rgb(color), 0))
            tinted.putalpha(image.getchannel("A"))
            _symbols[key] = tinted
        except Exception:
            return None
    return ImageTk.PhotoImage(_symbols[key])


def reduce_motion():
    try:
        from AppKit import NSWorkspace
        return bool(NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion())
    except Exception:
        return False


class RecordingAction(tk.Canvas):
    def __init__(self, master, symbol, label, command, primary=False):
        super().__init__(master, width=44, height=44, bg=master.cget("bg"),
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=True)
        self.command = command
        color = THEME["primary_fg"] if primary else THEME["accent"]
        self.photo = symbol_photo(symbol, color)
        if primary: self.create_oval(2, 2, 42, 42, fill=THEME["primary"], outline="")
        if self.photo: self.create_image(22, 22, image=self.photo)
        else: self.create_text(22, 22, text=label, fill=color, font=ui_font(9))
        self.bind("<Button-1>", lambda _: command())
        self.bind("<Return>", lambda _: command())
        self.bind("<space>", lambda _: command())
        # Tooltip is a label within this widget, never an extra native window.
        self.bind("<Enter>", lambda _: self.configure(cursor="hand2"))


class RecordingHints(tk.Canvas):
    def __init__(self, master, cancel):
        super().__init__(master, height=96, bg=THEME["surface"], highlightthickness=0, bd=0)
        self.cancel = cancel
        self.locked = False
        self.dx = self.dy = 0
        self.lock_x = None
        self.indicator_color = THEME["danger"]
        self.message = False
        self.reduced_motion = reduce_motion()
        self.reveal = 0 if not self.reduced_motion else 1
        self.images = {name: symbol_photo(name, THEME["muted"], 18) for name in ("lock.open", "lock.fill", "chevron.up", "chevron.left")}
        self.job = None
        self.bind("<Configure>", lambda _: self.render())
        self.bind("<Button-1>", self.click)
        self.bind("<Destroy>", self.cleanup)
        self.started = time.monotonic()
        self.animate()

    def animate(self):
        self.reveal = min(1, (time.monotonic() - self.started) / 0.2) if not self.reduced_motion else 1
        self.render()
        self.job = self.after(16, self.animate) if self.reveal < 1 else None

    def update_drag(self, dx=0, dy=0, locked=False, lock_x=None):
        self.dx, self.dy, self.locked, self.lock_x = dx, dy, locked, lock_x
        self.configure(height=44 if locked else 96)
        self.render()

    def render(self):
        self.delete("all")
        if self.message: return
        width = max(240, self.winfo_width())
        progress = min(1, max(0, -self.dx / 96))
        fg = mix_hex(THEME["surface"], THEME["danger"] if progress > 0.65 else THEME["muted"], self.reveal * (1 - progress * 0.6))
        x = max(178, width * 0.52) + max(-36, self.dx * 0.35)
        y = 22 if self.locked else 74
        self.create_oval(12, y - 4, 20, y + 4, fill=self.indicator_color, outline="")
        if self.locked:
            self.create_text(x, 22, text="Отмена", fill=THEME["accent"], font=ui_font(17), tags="cancel")
            self.configure(cursor="hand2")
        else:
            self.create_text(x, 74, text="‹  Сдвиньте для отмены", fill=fg, font=ui_font(14))
            lockness = min(1, max(0, -self.dy / 80))
            lock_x = max(24, min(width - 24, self.lock_x if self.lock_x is not None else width - 30))
            top = 4 - lockness * 3 + (1 - self.reveal) * 8
            bottom = 56 - lockness * 16
            color = mix_hex(THEME["surface"], THEME["surface_alt"], self.reveal)
            self.create_oval(lock_x - 18, top, lock_x + 18, top + 36, fill=color, outline="")
            self.create_rectangle(lock_x - 18, top + 18, lock_x + 18, bottom - 18, fill=color, outline="")
            self.create_oval(lock_x - 18, bottom - 36, lock_x + 18, bottom, fill=color, outline="")
            image = self.images["lock.fill" if lockness > 0.7 else "lock.open"]
            if image: self.create_image(lock_x, top + 17, image=image)
            if lockness < 0.7 and self.images["chevron.up"]:
                self.create_image(lock_x, bottom - 13, image=self.images["chevron.up"])
            self.configure(cursor="")

    def click(self, event):
        if self.locked and "cancel" in self.gettags("current"): self.cancel()

    def cleanup(self, event):
        if event.widget is self and self.job:
            self.after_cancel(self.job)
            self.job = None
