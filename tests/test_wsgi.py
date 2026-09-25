import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from chat_server.wsgi import create_application


class WSGITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "chat.sqlite3"
        self.app = create_application(self.path)

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

    def test_delivery_and_persistence(self):
        for name in ("alice", "bob"):
            self.assertEqual(self.request("/v1/profile/claim", {"username": name,
                "display_name": name, "owner_token": name * 32})[0], 200)
        status, message = self.request("/v1/messages/send", {"sender": "alice",
            "recipient": "bob", "client_id": "test-1", "body": "Привет", "owner_token": "alice" * 32})
        self.assertEqual(status, 200)
        self.app.database.close()
        self.app = create_application(self.path)
        status, result = self.request("/v1/sync", {"username": "bob", "owner_token": "bob" * 32})
        self.assertEqual(result["events"][0]["message"]["body"], "Привет")
        self.assertEqual(self.request("/v1/messages/ack", {"username": "bob",
            "owner_token": "bob" * 32, "message_ids": [message["id"]], "status": "read"})[0], 200)
        self.assertEqual(self.request("/v1/admin/reset", {})[0], 404)
        self.assertEqual(self.request("/v1/sync", {"username": "bob", "owner_token": "wrong"})[0], 401)

    def test_sync_never_holds_single_worker(self):
        self.request("/v1/profile/claim", {"username": "alice", "display_name": "Alice", "owner_token": "a" * 64})
        started = time.monotonic()
        self.assertEqual(self.request("/v1/sync", {"username": "alice", "owner_token": "a" * 64,
            "after_event": 999999, "wait_ms": 25000})[0], 200)
        self.assertLess(time.monotonic() - started, 1)
