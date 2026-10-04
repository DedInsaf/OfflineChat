import unittest
from unittest.mock import patch
from desktop_chat.application import App


class OnlineProfileRefreshTests(unittest.TestCase):
    def setUp(self):
        self.app = App.__new__(App)
        self.profile = {"name": "alice", "display_name": "Alice", "bio": "", "avatar_base64": None, "last_seen": 10, "_stamp": 1}
        self.app.online_profiles = {"alice": dict(self.profile)}
        self.app._online_list_sig = "unchanged"
        self.app._list_dirty = False

    def test_presence_poll_does_not_rebuild_list_or_write_profiles(self):
        incoming = dict(self.profile, last_seen=20)
        incoming.pop("_stamp")
        with patch("desktop_chat.application.save_online_profiles") as save:
            self.app.handle({"event": "online_profile", "profile": incoming})
        self.assertEqual(self.app.online_profiles["alice"]["last_seen"], 20)
        self.assertEqual(self.app.online_profiles["alice"]["_stamp"], 1)
        self.assertFalse(self.app._list_dirty)
        self.assertEqual(self.app._online_list_sig, "unchanged")
        save.assert_not_called()

    def test_changed_avatar_refreshes_list(self):
        incoming = dict(self.profile, avatar_base64="new-avatar")
        incoming.pop("_stamp")
        with patch("desktop_chat.application.save_online_profiles") as save:
            self.app.handle({"event": "online_profile", "profile": incoming})
        self.assertTrue(self.app._list_dirty)
        self.assertIsNone(self.app._online_list_sig)
        self.assertGreater(self.app.online_profiles["alice"]["_stamp"], 1)
        save.assert_called_once()
