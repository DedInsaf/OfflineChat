import os
import tempfile
import unittest

from chat_server import ChatDatabase, ChatDatabaseError


class ChatDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = ChatDatabase(os.path.join(self.directory.name, "chat.sqlite3"))
        self.alice_token = self.register("alice")
        self.bob_token = self.register("bob")

    def register(self, name):
        challenge, _address, code = self.database.start_registration(
            name, name + "@example.com", "securepass1", "securepass1", name.title()
        )
        return self.database.verify_challenge(challenge["challenge_id"], code, "register")["session_token"]

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

    def test_session_protects_profile(self):
        with self.assertRaises(ChatDatabaseError):
            self.database.update_profile("alice", "alice", "Not Alice", "", None, self.bob_token)

    def test_password_and_email_code_are_required(self):
        challenge, _address, code = self.database.start_login("alice", "securepass1")
        with self.assertRaises(ChatDatabaseError):
            self.database.verify_challenge(challenge["challenge_id"], "000000", "login")
        session = self.database.verify_challenge(challenge["challenge_id"], code, "login")["session_token"]
        self.assertEqual(self.database.sync("alice", session, 0)["cursor"], 0)
        with self.assertRaises(ChatDatabaseError):
            self.database.start_login("alice", "wrong-password")

    def test_reset_removes_all_server_data(self):
        self.database.send("alice", "bob", "request-3", "Удалить", self.alice_token)
        self.database.reset()
        self.assertEqual(self.database.counts(), {"profiles": 0, "messages": 0, "events": 0,
                                                  "auth_accounts": 0, "auth_sessions": 0})


if __name__ == "__main__":
    unittest.main()
