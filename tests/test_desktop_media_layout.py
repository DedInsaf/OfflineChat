"""Tk geometry and state regressions, without using camera or microphone."""
import os
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import Mock

from PIL import Image
from desktop_chat.photos import PhotoPreview
from desktop_chat.recording import RecordingButton


class DesktopMediaLayoutTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("500x400")

    def tearDown(self):
        self.root.destroy()

    def test_recording_timer_and_lock_are_visible_above_input(self):
        bar = tk.Frame(self.root)
        bar.pack(fill="x")
        composer = tk.Frame(bar)
        composer.pack(fill="x")
        button = RecordingButton(composer, Mock(), Mock(), status_host=bar)
        button.pack()
        button.process = Mock()
        button.started = time.monotonic() - 7
        button.show_status()
        self.root.update()
        self.assertIn("Голос  00:07", button.status_label.cget("text"))
        self.assertLess(button.panel.winfo_y(), composer.winfo_y())
        button.locked = True
        button.show_actions()
        self.assertIn("Запись закреплена", button.status_label.cget("text"))
        button.process = None
        button.clear_actions()
        self.assertIsNone(button.panel)
        self.assertIsNone(button.timer_job)

    def test_preview_respects_exif_rotation_and_viewport(self):
        viewport = tk.Canvas(self.root, width=240, height=300)
        viewport.pack()
        self.root.update()
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "rotated.jpg")
            image = Image.new("RGB", (600, 300), "red")
            exif = image.getexif()
            exif[274] = 6
            image.save(path, exif=exif)
            preview = PhotoPreview(self.root, path, viewport)
            preview.pack()
            self.root.update()
            self.assertGreater(preview.image.height(), preview.image.width())
            viewport.configure(width=100)
            self.root.update()
            preview.render()
            self.assertLessEqual(preview.image.width(), viewport.winfo_width() - 52)
            preview.destroy()
