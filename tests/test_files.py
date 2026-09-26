import base64
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from chat_server.database import MAX_FILE_BYTES
from chat_server.wsgi import create_application
from online_chat.files import stage, discard


class FileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "chat.sqlite3"
        self.app = create_application(self.path)
        for name in ("alice", "bob", "eve"):
            self.request("profile/claim", {"username": name, "owner_token": name * 32})

    def tearDown(self):
        self.app.database.close()
        self.directory.cleanup()

    def request(self, route, body):
        raw = json.dumps(body).encode()
        statuses = []
        result = self.app({"REQUEST_METHOD": "POST", "PATH_INFO": "/v1/" + route,
                           "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)},
                          lambda status, headers: statuses.append(int(status.split()[0])))
        return statuses[0], json.loads(b"".join(result))

    def send(self, content=b"\x00\xffHello", name="Документ.bin", client_id="file-1"):
        return self.request("messages/send", {"sender": "alice", "recipient": "bob", "body": "",
            "client_id": client_id, "owner_token": "alice" * 32,
            "attachment": {"name": name, "data_base64": base64.b64encode(content).decode()}})

    def download(self, who, mid):
        return self.request("files/download", {"username": who, "owner_token": who * 32, "message_id": mid})

    def test_roundtrip_acl_idempotency_and_restart(self):
        content = bytes(range(256)) * 1024
        status, sent = self.send(content)
        self.assertEqual(status, 200)
        self.assertEqual(sent["attachment"]["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(self.send(content)[1]["id"], sent["id"])
        self.assertEqual(self.app.database.counts()["messages"], 1)
        self.assertEqual(self.download("eve", sent["id"])[0], 404)
        self.assertEqual(self.request("files/download", {"username": "bob", "owner_token": "x" * 64,
            "message_id": sent["id"]})[0], 403)
        self.app.database.close()
        self.app = create_application(self.path)
        for user in ("alice", "bob"):
            status, downloaded = self.download(user, sent["id"])
            self.assertEqual(status, 200)
            self.assertEqual(base64.b64decode(downloaded["data_base64"]), content)
        _, synced = self.request("sync", {"username": "bob", "owner_token": "bob" * 32})
        self.assertNotIn("data_base64", json.dumps(synced))
        self.assertEqual(synced["events"][0]["message"]["attachment"], sent["attachment"])
        for receipt in ("delivered", "read"):
            self.assertEqual(self.request("messages/ack", {"username": "bob", "owner_token": "bob" * 32,
                "message_ids": [sent["id"]], "status": receipt})[0], 200)
        self.request("profile/update", {"username": "bob", "new_username": "bobby", "owner_token": "bob" * 32})
        self.assertEqual(self.request("files/download", {"username": "bobby", "owner_token": "bob" * 32,
            "message_id": sent["id"]})[0], 200)

    def test_limits_validation_and_transaction_rollback(self):
        self.assertEqual(self.send(b"")[0], 413)
        self.assertEqual(self.send(b"a" * MAX_FILE_BYTES)[0], 200)
        self.assertEqual(self.send(b"a" * (MAX_FILE_BYTES + 1), client_id="large")[0], 413)
        for name in ("../evil", "dir/file", "a\\b", "..", "bad\nname", "a" * 181):
            self.assertEqual(self.send(name=name, client_id=name)[0], 400)
        with patch("chat_server.database.MAX_ATTACHMENT_STORAGE", MAX_FILE_BYTES):
            self.assertEqual(self.send(client_id="quota")[0], 507)
        self.assertEqual(self.app.database.counts()["messages"], 1)
        self.assertEqual(self.send(client_id="after-quota")[0], 200)

    def test_invalid_base64_and_text_compatibility(self):
        self.assertEqual(self.request("messages/send", {"sender": "alice", "recipient": "bob", "client_id": "bad",
            "owner_token": "alice" * 32, "attachment": {"name": "x", "data_base64": "!!!!"}})[0], 400)
        status, sent = self.request("messages/send", {"sender": "alice", "recipient": "bob", "client_id": "text",
            "owner_token": "alice" * 32, "body": "Привет"})
        self.assertEqual(status, 200)
        self.assertIsNone(sent["attachment"])
        self.assertEqual(self.download("bob", sent["id"])[0], 404)

    def test_old_database_migration(self):
        self.app.database.close()
        con = sqlite3.connect(self.path)
        con.execute("ALTER TABLE messages DROP COLUMN attachment")
        con.commit()
        con.close()
        self.app = create_application(self.path)
        self.assertEqual(self.send()[0], 200)

    def test_upload_copy_survives_changed_original(self):
        source = Path(self.directory.name) / "original.bin"
        source.write_bytes(b"first")
        request_id = str(uuid.uuid4())
        copied = stage(source, request_id, Path(self.directory.name) / "uploads")
        source.write_bytes(b"changed")
        self.assertEqual(stage(source, request_id, Path(self.directory.name) / "uploads"), copied)
        self.assertEqual(Path(copied).read_bytes(), b"first")
        discard(copied)
        self.assertFalse(Path(copied).exists())
