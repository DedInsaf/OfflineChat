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
from chat_server.emailer import MemoryCodeSender
from chat_server.wsgi import create_application
from online_chat.files import stage, discard

try:
    from PIL import Image
except ImportError:
    Image = None


class FileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "chat.sqlite3"
        self.sender = MemoryCodeSender()
        self.app = create_application(self.path, self.sender)
        self.tokens = {}
        for name in ("alice", "bob", "eve"):
            self.tokens[name] = self.register(name)

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

    def register(self, name):
        status, challenge = self.request("auth/register/start", {
            "username": name, "email": name + "@example.com", "password": "securepass1",
            "password_confirmation": "securepass1", "display_name": name.title(),
        })
        self.assertEqual(status, 200)
        code = self.sender.messages[-1]["code"]
        status, session = self.request("auth/register/verify", {
            "challenge_id": challenge["challenge_id"], "code": code,
        })
        self.assertEqual(status, 200)
        return session["session_token"]

    def send(self, content=b"\x00\xffHello", name="Документ.bin", client_id="file-1"):
        return self.request("messages/send", {"sender": "alice", "recipient": "bob", "body": "",
            "client_id": client_id, "session_token": self.tokens["alice"],
            "attachment": {"name": name, "data_base64": base64.b64encode(content).decode()}})

    def download(self, who, mid):
        return self.request("files/download", {"username": who, "session_token": self.tokens[who], "message_id": mid})

    def test_roundtrip_acl_idempotency_and_restart(self):
        content = bytes(range(256)) * 1024
        status, sent = self.send(content)
        self.assertEqual(status, 200)
        self.assertEqual(sent["attachment"]["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(self.send(content)[1]["id"], sent["id"])
        self.assertEqual(self.app.database.counts()["messages"], 1)
        self.assertEqual(self.download("eve", sent["id"])[0], 404)
        self.assertEqual(self.request("files/download", {"username": "bob", "session_token": "x" * 64,
            "message_id": sent["id"]})[0], 401)
        self.app.database.close()
        self.app = create_application(self.path, self.sender)
        for user in ("alice", "bob"):
            status, downloaded = self.download(user, sent["id"])
            self.assertEqual(status, 200)
            self.assertEqual(base64.b64decode(downloaded["data_base64"]), content)
        _, synced = self.request("sync", {"username": "bob", "session_token": self.tokens["bob"]})
        self.assertNotIn("data_base64", json.dumps(synced))
        self.assertEqual(synced["events"][0]["message"]["attachment"], sent["attachment"])
        for receipt in ("delivered", "read"):
            self.assertEqual(self.request("messages/ack", {"username": "bob", "session_token": self.tokens["bob"],
                "message_ids": [sent["id"]], "status": receipt})[0], 200)
        self.request("profile/update", {"username": "bob", "new_username": "bobby", "session_token": self.tokens["bob"]})
        self.assertEqual(self.request("files/download", {"username": "bobby", "session_token": self.tokens["bob"],
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
            "session_token": self.tokens["alice"], "attachment": {"name": "x", "data_base64": "!!!!"}})[0], 400)
        status, sent = self.request("messages/send", {"sender": "alice", "recipient": "bob", "client_id": "text",
            "session_token": self.tokens["alice"], "body": "Привет"})
        self.assertEqual(status, 200)
        self.assertIsNone(sent["attachment"])
        self.assertEqual(self.download("bob", sent["id"])[0], 404)

    def test_old_database_migration(self):
        self.app.database.close()
        con = sqlite3.connect(self.path)
        con.execute("ALTER TABLE messages DROP COLUMN attachment")
        con.commit()
        con.close()
        self.app = create_application(self.path, self.sender)
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

    @unittest.skipIf(Image is None, "Pillow is not installed")
    def test_photo_is_optimized_for_media_message(self):
        source = Path(self.directory.name) / "camera.png"
        Image.new("RGB", (2600, 1800), (80, 160, 220)).save(source, "PNG")
        copied = Path(stage(source, str(uuid.uuid4()), Path(self.directory.name) / "uploads", media_kind="photo"))
        self.assertEqual(copied.suffix, ".jpg")
        self.assertLess(copied.stat().st_size, source.stat().st_size)
        with Image.open(copied) as optimized:
            self.assertLessEqual(max(optimized.size), 1920)
