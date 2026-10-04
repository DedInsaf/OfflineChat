"""Recording gestures must never accidentally send a discarded recording."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from desktop_chat.recording import RecordingButton


class RecordingGestureTests(unittest.TestCase):
    def control(self):
        button = RecordingButton.__new__(RecordingButton)
        button.origin = (200, 200)
        button.locked = False
        button.cancelled = False
        button.job = None
        button.video = False
        button.finish = Mock()
        button.cancel = Mock()
        button.show_mode = Mock()
        button.show_actions = Mock()
        button.hints = None
        button.start = Mock()
        button.lock_position = Mock()
        return button

    def test_slide_up_keeps_recording_after_release(self):
        button = self.control()
        button.drag(SimpleNamespace(x_root=200, y_root=120))
        button.release(None)
        self.assertTrue(button.locked)
        button.show_actions.assert_called_once()
        button.finish.assert_not_called()

    def test_slide_left_discards_and_release_does_not_send(self):
        button = self.control()
        button.drag(SimpleNamespace(x_root=100, y_root=200))
        button.release(None)
        button.cancel.assert_called_once()
        button.finish.assert_not_called()

    def test_short_press_only_changes_mode(self):
        button = self.control()
        button.job = "pending"
        button.after_cancel = Mock()
        button.release(None)
        self.assertTrue(button.video)
        button.after_cancel.assert_called_once_with("pending")
        button.finish.assert_not_called()

    def test_locked_recording_ignores_left_drag(self):
        button = self.control()
        button.locked = True
        button.drag(SimpleNamespace(x_root=100, y_root=200))
        button.cancel.assert_not_called()

    def test_fast_upward_gesture_starts_and_locks_instead_of_losing_capture(self):
        button = self.control()
        button.job = "pending"
        button.after_cancel = Mock()
        button.drag(SimpleNamespace(x_root=200, y_root=100))
        button.release(None)
        button.start.assert_called_once()
        button.finish.assert_not_called()

    def test_small_movement_does_not_cancel_or_lock(self):
        button = self.control()
        button.drag(SimpleNamespace(x_root=170, y_root=180))
        self.assertFalse(button.locked)
        button.cancel.assert_not_called()
