"""Inline recorded messages. Tk owns presentation; AVPlayer owns audio timing."""
import array
import os
import queue
import shutil
import subprocess
import threading
import tkinter as tk

from .shared import THEME, ui_font, Image, ImageTk


class RecordedMessage(tk.Canvas):
    def __init__(self, master, path, circle=False):
        self.circle = circle
        self.side = 200
        super().__init__(master, width=200 if circle else 330, height=200 if circle else 78,
                         bg=THEME["chat_bg"], highlightthickness=0, cursor="hand2")
        from AVFoundation import AVPlayer
        from Foundation import NSURL
        self.player = AVPlayer.playerWithURL_(NSURL.fileURLWithPath_(path))
        self.path = path
        self.playing = False
        self.closed = False
        self.duration = 0
        self.waveform = []
        self.frames = queue.Queue(maxsize=2)
        self.results = queue.Queue()
        self.frame = None
        self.decoder = None
        self.generation = 0
        self.executable = shutil.which("ffmpeg") or ("/opt/homebrew/bin/ffmpeg" if os.path.isfile("/opt/homebrew/bin/ffmpeg") else None)
        self.bind("<Button-1>", self.toggle)
        self.bind("<Destroy>", self.destroy_player)
        if circle: self.decode_video(0, preview=True)
        else: threading.Thread(target=self.read_waveform, daemon=True).start()
        self.tick()

    def read_waveform(self):
        if not self.executable: return
        result = subprocess.run([self.executable, "-v", "error", "-i", self.path, "-t", "60", "-vn", "-ac", "1", "-ar", "8000", "-f", "f32le", "pipe:1"], capture_output=True, timeout=30)
        values = array.array("f")
        values.frombytes(result.stdout[:len(result.stdout) // 4 * 4])
        if values:
            bars = [max(abs(value) for value in values[index * len(values) // 48:max(index * len(values) // 48 + 1, (index + 1) * len(values) // 48)]) for index in range(48)]
            peak = max(max(bars), 0.01)
            self.results.put([value / peak for value in bars])

    def position(self):
        time = self.player.currentTime()
        return time.value / time.timescale if time.timescale else 0

    def decode_video(self, offset, preview=False):
        if not self.executable or Image is None: return
        self.generation += 1
        generation = self.generation
        if self.decoder and self.decoder.poll() is None: self.decoder.terminate()
        arguments = [self.executable, "-v", "error"]
        if not preview: arguments += ["-re"]
        arguments += ["-ss", str(offset), "-i", self.path, "-an", "-vf", "fps=15,crop=min(iw\\,ih):min(iw\\,ih),scale=300:300"]
        if preview: arguments += ["-frames:v", "1"]
        arguments += ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.decoder = process
        def decode():
            try:
                while not self.closed and generation == self.generation:
                    data = process.stdout.read(300 * 300 * 3)
                    if len(data) != 300 * 300 * 3: break
                    frame = Image.frombytes("RGB", (300, 300), data)
                    try: self.frames.put_nowait(frame)
                    except queue.Full:
                        try: self.frames.get_nowait()
                        except queue.Empty: pass
                        try: self.frames.put_nowait(frame)
                        except queue.Full: pass
            finally:
                process.stdout.close()
                if process.poll() is None: process.terminate()
                process.wait()
        threading.Thread(target=decode, daemon=True).start()

    def toggle(self, _event=None):
        if self.playing:
            self.player.pause()
            if self.decoder and self.decoder.poll() is None: self.decoder.terminate()
        else:
            if self.duration and self.position() >= self.duration - 0.2:
                from CoreMedia import CMTimeMakeWithSeconds
                self.player.seekToTime_(CMTimeMakeWithSeconds(0, 600))
            self.player.play()
            if self.circle: self.decode_video(self.position())
        self.playing = not self.playing

    def tick(self):
        if self.closed: return
        try:
            while True: self.frame = self.frames.get_nowait()
        except queue.Empty: pass
        try: self.waveform = self.results.get_nowait()
        except queue.Empty: pass
        duration = self.player.currentItem().duration()
        if duration.timescale:
            self.duration = max(0, duration.value / duration.timescale)
        elapsed = max(0, self.position())
        if self.duration > 0 and elapsed >= self.duration - 0.1: self.playing = False
        self.delete("all")
        seconds = int(elapsed if elapsed > 0 else self.duration)
        label = "%02d:%02d" % (seconds // 60, seconds % 60)
        if self.circle:
            target = 280 if self.playing else 200
            self.side += max(-12, min(12, target - self.side))
            side = self.side
            self.configure(width=side, height=side)
            if self.frame:
                from PIL import ImageDraw
                frame = self.frame.resize((side, side), Image.Resampling.LANCZOS).convert("RGBA")
                mask = Image.new("L", (side, side))
                ImageDraw.Draw(mask).ellipse((0, 0, side - 1, side - 1), fill=255)
                frame.putalpha(mask)
                self.photo = ImageTk.PhotoImage(frame)
                self.create_image(0, 0, anchor="nw", image=self.photo)
            else: self.create_oval(1, 1, side - 1, side - 1, fill="#171A1F", outline="")
            if not self.playing: self.create_text(side / 2, side / 2, text="▶", fill="white", font=ui_font(26))
            self.create_text(side / 2, side - 24, text=label, fill="white", font=ui_font(12))
        else:
            self.create_oval(8, 9, 68, 69, fill="#693BFF", outline="")
            self.create_text(38, 38, text="Ⅱ" if self.playing else "▶", fill="white", font=ui_font(22))
            for index in range(48):
                height = max(3, (self.waveform[index] if self.waveform else 0) * 24)
                x = 84 + index * 4.8
                self.create_line(x, 37, x, 37 - height, width=3,
                                 fill="#986FFF" if index / 48 < elapsed / max(self.duration, 1) else "#9199AD")
            self.create_text(84, 55, text=label, fill="#AEBACD", anchor="w", font=ui_font(14))
        self.after(65, self.tick)

    def destroy_player(self, event):
        if event.widget is not self: return
        self.closed = True
        self.player.pause()
        if self.decoder and self.decoder.poll() is None: self.decoder.terminate()
