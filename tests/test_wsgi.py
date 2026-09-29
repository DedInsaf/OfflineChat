import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from chat_server.wsgi import create_application
from chat_server.emailer import MemoryCodeSender


class WSGITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "chat.sqlite3"
        self.sender = MemoryCodeSender()
        self.app = create_application(self.path, self.sender)
        self.tokens = {}

    def tearDown(self):
        self.app.database.close()
        self.directory.cleanup()

    def request(self, path, body):
        data = json.dumps(body).encode()
        statuses = []
        result = self.app({"PATH_INFO": path, "REQUEST_METHOD": "POST",
                           "CONTENT_LENGTH": str(len(data)), "wsgi.input": io.BytesIO(data)},
                          lambda status, headers: statuses.append(status))
        return int(statuses[0].split()[0]), json.loads(b"".join(result))

    def register(self, name):
        status, challenge = self.request("/v1/auth/register/start", {
            "username": name, "email": name + "@example.com", "password": "securepass1",
            "password_confirmation": "securepass1", "display_name": name.title(),
        })
        self.assertEqual(status, 200)
        status, result = self.request("/v1/auth/register/verify", {
            "challenge_id": challenge["challenge_id"], "code": self.sender.messages[-1]["code"],
        })
        self.assertEqual(status, 200)
        self.tokens[name] = result["session_token"]

    def test_delivery_and_persistence(self):
        for name in ("alice", "bob"):
            self.register(name)
        status, message = self.request("/v1/messages/send", {"sender": "alice",
            "recipient": "bob", "client_id": "test-1", "body": "Привет", "session_token": self.tokens["alice"]})
        self.assertEqual(status, 200)
        self.app.database.close()
        self.app = create_application(self.path, self.sender)
        status, result = self.request("/v1/sync", {"username": "bob", "session_token": self.tokens["bob"]})
        self.assertEqual(result["events"][0]["message"]["body"], "Привет")
        self.assertEqual(self.request("/v1/messages/ack", {"username": "bob",
            "session_token": self.tokens["bob"], "message_ids": [message["id"]], "status": "read"})[0], 200)
        self.assertEqual(self.request("/v1/admin/reset", {})[0], 404)
        self.assertEqual(self.request("/v1/sync", {"username": "bob", "session_token": "wrong"})[0], 401)

    def test_sync_never_holds_single_worker(self):
        self.register("alice")
        started = time.monotonic()
        self.assertEqual(self.request("/v1/sync", {"username": "alice", "session_token": self.tokens["alice"],
            "after_event": 999999, "wait_ms": 25000})[0], 200)
        self.assertLess(time.monotonic() - started, 1)
