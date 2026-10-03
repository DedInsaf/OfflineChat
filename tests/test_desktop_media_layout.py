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
from desktop_chat.shared import THEME, build_palette, DARK_BASE, LIGHT_BASE, luminance
from desktop_chat.capture_preview import CapturePreview
import queue
from types import SimpleNamespace


class DesktopMediaLayoutTests(unittest.TestCase):
    def setUp(self):
        THEME.update(build_palette(**DARK_BASE))
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
        button.process.poll.return_value = None
        button.started = time.monotonic() - 7
        button.show_status()
        self.root.update()
        self.assertIn("Голосовое  00:07", button.status_label.cget("text"))
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

    def test_video_capture_preview_has_transparent_corners(self):
        feed = SimpleNamespace(frames=queue.Queue(), level=0.5)
        feed.frames.put(Image.new("RGB", (176, 176), "red"))
        preview = CapturePreview(self.root, feed, True)
        preview.pack()
        self.root.update()
        self.assertIsNotNone(preview.photo)
        self.assertTrue(preview.tk.getboolean(preview.tk.call(str(preview.photo), "transparency", "get", 0, 0)))
        self.assertFalse(preview.tk.getboolean(preview.tk.call(str(preview.photo), "transparency", "get", 88, 88)))

    def test_recording_controls_follow_light_and_dark_theme(self):
        for base in (LIGHT_BASE, DARK_BASE):
            THEME.update(build_palette(**base))
            button = RecordingButton(self.root, Mock(), Mock(), bg=THEME["surface"])
            button.show_status("↑ Закрепить   ·   ← Отменить")
            self.assertEqual(button.status_label.cget("fg"), THEME["text"])
            self.assertEqual(button.status_label.cget("bg"), THEME["surface"])
            self.assertGreater(abs(luminance(THEME["text"]) - luminance(THEME["surface"])), 0.4)
            button.destroy()
