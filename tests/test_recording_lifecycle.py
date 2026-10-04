import io
import os
import queue
import threading
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from desktop_chat.recording import RecordingButton
from desktop_chat.shared import THEME, build_palette, DARK_BASE


class RecordingLifecycleTests(unittest.TestCase):
    def setUp(self):
        THEME.update(build_palette(**DARK_BASE))
        self.root = tk.Tk()
        self.send, self.report = Mock(), Mock()
        self.button = RecordingButton(self.root, self.send, self.report)
        self.button.pack()
        self.paths = []
        self.wait_gate = threading.Event()
        self.wait_gate.set()

        def spawn(arguments, **kwargs):
            path = next(arg for arg in arguments if arg.endswith(".m4a"))
            self.paths.append(path)
            with open(path, "wb") as file: file.write(b"x" * 2048)
            process = Mock()
            process.stdin = io.BytesIO()
            process.poll.return_value = None
            process.wait.side_effect = lambda **kwargs: self.wait_gate.wait(timeout=2)
            return process

        self.popen = patch("desktop_chat.recording.subprocess.Popen", side_effect=spawn)
        self.feed = patch("desktop_chat.recording.CaptureFeed", side_effect=lambda *_: SimpleNamespace(frames=queue.Queue(), level=0.2, ready=True, closed=False))
        self.popen.start(); self.feed.start()

    def tearDown(self):
        self.wait_gate.set()
        self.button.cancel()
        self.root.destroy()
        self.popen.stop(); self.feed.stop()
        for path in self.paths:
            if os.path.isfile(path): os.unlink(path)

    def settle(self):
        deadline = time.monotonic() + 2
        while self.button.finalizing and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.button.finalizing)

    def begin(self):
        self.button.start()
        self.button.started -= 1

    def test_pause_resume_sends_only_when_explicitly_finished(self):
        self.begin()
        self.button.locked = True
        self.button.pause()
        self.settle()
        self.assertTrue(self.button.paused)
        self.assertTrue(self.button.locked)
        self.send.assert_not_called()
        self.button.start(resuming=True)
        self.button.started -= 1
        self.assertFalse(self.button.paused)
        with patch("desktop_chat.recording.join_segments", side_effect=lambda _exe, paths, _video: paths[-1]):
            self.button.finish()
            self.settle()
        self.send.assert_called_once()
        self.report.assert_not_called()

    def test_cancel_while_finalizing_never_sends_and_reenables_recording(self):
        self.begin()
        self.wait_gate.clear()
        start = time.monotonic()
        self.button.finish()
        self.assertLess(time.monotonic() - start, 0.1)
        self.assertTrue(self.button.finalizing)
        self.button.cancel()
        self.wait_gate.set()
        self.settle()
        self.send.assert_not_called()
        self.assertTrue(all(not os.path.isfile(path) for path in self.paths))
        self.begin()
        self.assertIsNotNone(self.button.process)

    def test_draft_requires_explicit_send(self):
        self.begin()
        # Avoid initializing a real player; capture is already a mock.
        with patch("desktop_chat.playback.RecordedMessage", return_value=Mock()):
            self.button.finish(review=True)
            self.settle()
            self.assertIsNotNone(self.button.draft)
            self.send.assert_not_called()
            self.button.send_draft()
        self.send.assert_called_once()
