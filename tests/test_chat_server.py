import os
import tempfile
import unittest

from chat_server import ChatDatabase, ChatDatabaseError


class ChatDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = ChatDatabase(os.path.join(self.directory.name, "chat.sqlite3"))
        self.alice_token = "a" * 64
        self.bob_token = "b" * 64
        self.database.claim("alice", "Alice", self.alice_token)
        self.database.claim("bob", "Bob", self.bob_token)

    def tearDown(self):
        self.database.close()
        self.directory.cleanup()

    def test_send_is_idempotent_and_visible_to_both_users(self):
        first, first_changed = self.database.send("alice", "bob", "request-1", "Привет", self.alice_token)
        second, second_changed = self.database.send("alice", "bob", "request-1", "Привет", self.alice_token)

        self.assertTrue(first_changed)
        self.assertFalse(second_changed)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.database.counts()["messages"], 1)
        self.assertEqual(len(self.database.sync("alice", self.alice_token, 0)["events"]), 1)
        self.assertEqual(len(self.database.sync("bob", self.bob_token, 0)["events"]), 1)

    def test_receipts_are_monotonic_and_only_recipient_can_set_them(self):
        message, _ = self.database.send("alice", "bob", "request-2", "Тест", self.alice_token)
        changed, _ = self.database.acknowledge("bob", self.bob_token, [message["id"]], "read")
        self.assertEqual(changed, [message["id"]])
        changed, _ = self.database.acknowledge("bob", self.bob_token, [message["id"]], "delivered")
        self.assertEqual(changed, [])
        latest = self.database.sync("alice", self.alice_token, 0)["events"][-1]["message"]
        self.assertEqual(latest["status"], "read")

    def test_unacknowledged_message_replays_after_cursor_advance(self):
        message, _ = self.database.send("alice", "bob", "request-replay", "Ещё здесь", self.alice_token)
        first = self.database.sync("bob", self.bob_token, 0)
        replay = self.database.sync("bob", self.bob_token, first["cursor"])
        self.assertEqual(replay["events"][0]["message"]["id"], message["id"])

    def test_owner_token_protects_profile(self):
        with self.assertRaises(ChatDatabaseError):
            self.database.claim("alice", "Not Alice", self.bob_token)

    def test_reset_removes_all_server_data(self):
        self.database.send("alice", "bob", "request-3", "Удалить", self.alice_token)
        self.database.reset()
        self.assertEqual(self.database.counts(), {"profiles": 0, "messages": 0, "events": 0})


if __name__ == "__main__":
    unittest.main()
