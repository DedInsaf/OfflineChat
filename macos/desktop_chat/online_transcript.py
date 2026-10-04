"""Online-only tail following and coalesced pixel scrolling."""
import tkinter as tk
from .shared import OnlineScrollFrame, THEME
from .recording_ui import symbol_photo


class OnlineTranscript(OnlineScrollFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.follow_tail = True
        self.near_bottom = True
        self.pending_messages = 0
        self._layout_job = self._scroll_job = None
        self._pending_pixels = 0
        self._closed = False
        self.canvas.configure(yscrollincrement=1, yscrollcommand=self._position_changed)
        self.vsb.configure(command=self._scrollbar)
        # A configure storm (text wrapping, photos, window resizing) becomes one
        # layout pass. The offline ScrollFrame implementation is left untouched.
        self.inner.bind("<Configure>", self._schedule_layout)
        self.canvas.bind("<Configure>", self._schedule_layout, add="+")
        self.down = tk.Canvas(self, width=44, height=44, bg=self.cget("bg"),
                              bd=0, highlightthickness=0, cursor="hand2", takefocus=True)
        self.down.create_oval(2, 2, 42, 42, fill=THEME["surface"], outline=THEME["line"])
        self.down_icon = symbol_photo("arrow.down", THEME["text"], 20)
        if self.down_icon: self.down.create_image(22, 22, image=self.down_icon)
        else: self.down.create_text(22, 22, text="↓", fill=THEME["text"])
        self.down.bind("<Button-1>", lambda _: self.scroll_to_end())
        self.down.bind("<Return>", lambda _: self.scroll_to_end())
        self.bind("<Destroy>", self._cleanup, add="+")

    def _schedule_layout(self, _event=None):
        if not self._closed and self._layout_job is None:
            self._layout_job = self.after_idle(self._layout)

    def _layout(self):
        self._layout_job = None
        if self._closed: return
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        if self.follow_tail: self.canvas.yview_moveto(1.0)
        self._position_changed(*self.canvas.yview())

    def _position_changed(self, first, last):
        self.vsb.set(first, last)
        if not hasattr(self, "down") or self._closed: return
        remaining = (1 - float(last)) * max(1, self.inner.winfo_height())
        near = remaining <= 64
        self.near_bottom = near
        if near:
            self.pending_messages = 0
            if self.down.winfo_manager(): self.down.place_forget()
        elif not self.down.winfo_manager():
            self.down.place(relx=1, rely=1, x=-24, y=-16, anchor="se")
            tk.Misc.lift(self.down)  # Canvas.lift raises canvas items, not widgets.

    def _scrollbar(self, *args):
        self.follow_tail = False
        self.canvas.yview(*args)
        self.follow_tail = self.canvas.yview()[1] >= 0.999

    def _wheel(self, event):
        number = getattr(event, "num", None)
        if number in (4, 5): pixels = -48 if number == 4 else 48
        else:
            delta = getattr(event, "delta", 0)
            if not delta: return "break"
            aqua = self.tk.call("tk", "windowingsystem") == "aqua"
            pixels = round(-delta * 4) if aqua and abs(delta) < 120 else round(-delta / 120 * 48)
        self.follow_tail = False
        self._pending_pixels += pixels
        if self._scroll_job is None: self._scroll_job = self.after(16, self._flush_scroll)
        return "break"

    def _flush_scroll(self):
        self._scroll_job = None
        if self._closed: return
        pixels, self._pending_pixels = self._pending_pixels, 0
        if self.inner.winfo_height() > self.canvas.winfo_height(): self.canvas.yview_scroll(pixels, "units")
        self.follow_tail = self.canvas.yview()[1] >= 0.999

    def message_added(self, outgoing=False):
        if outgoing or self.near_bottom:
            self.scroll_to_end()
        else:
            self.pending_messages += 1
            self._schedule_layout()

    def scroll_to_end(self):
        if self._closed: return
        if self._scroll_job: self.after_cancel(self._scroll_job); self._scroll_job = None
        self._pending_pixels = 0
        self.follow_tail = True
        self.pending_messages = 0
        self._schedule_layout()

    def _cleanup(self, event):
        if event.widget is not self: return
        self._closed = True
        for job in (self._layout_job, self._scroll_job):
            if job: self.after_cancel(job)


class MessageSelectionIndicator(tk.Canvas):
    """Reserved gutter: selecting never changes a bubble's size or position."""
    def __init__(self, master):
        super().__init__(master, width=28, height=28, bg=THEME["chat_bg"], highlightthickness=0, bd=0)
        self.icons = {False: symbol_photo("circle", THEME["muted"], 22),
                      True: symbol_photo("checkmark.circle.fill", THEME["accent"], 22)}
        self.state_key = None

    def set_selected(self, mode, selected, bg):
        key = (mode, selected, bg)
        if key == self.state_key: return
        self.state_key = key
        self.configure(bg=bg)
        self.delete("all")
        if mode:
            if self.icons[selected]: self.create_image(14, 14, image=self.icons[selected])
            else: self.create_text(14, 14, text="✓" if selected else "○", fill=THEME["accent"])
