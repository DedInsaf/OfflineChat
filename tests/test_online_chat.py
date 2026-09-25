import os
import tempfile
import unittest

from online_chat.models import merge_status, normalize_username, valid_username
from online_chat import storage


class UsernameTests(unittest.TestCase):
    def test_normalizes_supported_username(self):
        self.assertEqual(normalize_username("  @Anna-K_42 "), "annak_42")
        self.assertEqual(valid_username("@anna_42"), "anna_42")

    def test_rejects_short_numeric_and_cyrillic_usernames(self):
        self.assertIsNone(valid_username("ab"))
        self.assertIsNone(valid_username("42anna"))
        self.assertIsNone(valid_username("анна"))


class ReceiptTests(unittest.TestCase):
    def test_receipts_never_move_backwards(self):
        self.assertEqual(merge_status("read", "delivered"), "read")
        self.assertEqual(merge_status("sent", "delivered"), "delivered")


class StorageTests(unittest.TestCase):
    def test_chat_cache_is_atomic_and_filters_legacy_placeholders(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = storage.CHATS_PATH
            storage.CHATS_PATH = os.path.join(directory, "chats.json")
            try:
                storage.save_chats({"anna": [{"text": "Привет"}], "Команда": []})
                self.assertEqual(storage.load_chats(), {"anna": [{"text": "Привет"}]})
            finally:
                storage.CHATS_PATH = previous


if __name__ == "__main__":
    unittest.main()
