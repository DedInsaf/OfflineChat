import os
import tempfile
import threading
import unittest

from chat_server.database import ChatDatabase
from chat_server.server import ChatHTTPServer, ServerState
from chat_server.emailer import MemoryCodeSender
from online_chat.api import OnlineAPI


class ServerHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = ChatDatabase(os.path.join(self.directory.name, "chat.sqlite3"))
        self.sender = MemoryCodeSender()
        self.server = ChatHTTPServer(("127.0.0.1", 0), ServerState(self.database, self.sender))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.database.close()
        self.directory.cleanup()

    def register(self, api, name):
        challenge = api.start_registration(name, name + "@example.com", "securepass1", "securepass1", name.title())
        return api.verify_registration(challenge["challenge_id"], self.sender.messages[-1]["code"])["session_token"]

    def test_two_clients_exchange_and_acknowledge_message(self):
        alice = OnlineAPI(self.url)
        bob = OnlineAPI(self.url)
        alice_token = self.register(alice, "alice")
        bob_token = self.register(bob, "bob")

        sent = alice.send("alice", "bob", "http-request-1", "Привет", alice_token)
        received = bob.sync("bob", bob_token, 0)
        self.assertEqual(received["events"][0]["message"]["body"], "Привет")

        bob.acknowledge("bob", bob_token, [sent["id"]], "read")
        sender_events = alice.sync("alice", alice_token, 0)["events"]
        self.assertEqual(sender_events[-1]["message"]["status"], "read")
        alice.close()
        bob.close()

    def test_mac_file_api_roundtrip(self):
        from pathlib import Path
        path = Path(self.directory.name) / "hello.txt"
        path.write_bytes("Привет из файла".encode())
        api = OnlineAPI(self.url)
        try:
            alice_token = self.register(api, "alice")
            bob_token = self.register(api, "bob")
            message = api.send_file("alice", "bob", "file-http", path, alice_token)
            self.assertEqual(api.download_file("bob", bob_token, message["id"], message["attachment"]), path.read_bytes())
        finally:
            api.close()

    def test_reply_and_forward_metadata_survive_attachment_send(self):
        from pathlib import Path
        from online_chat.message_content import encode, decode
        path = Path(self.directory.name) / "forward.txt"
        path.write_bytes(b"forwarded data")
        api = OnlineAPI(self.url)
        try:
            alice_token = self.register(api, "alice")
            bob_token = self.register(api, "bob")
            reference = {"id": "source-client-id", "sender": "alice", "text": "Original"}
            body = encode("", reply=reference, forward=reference)
            sent = api.send_file("alice", "bob", "metadata-file", path, alice_token, text=body)
            received = api.sync("bob", bob_token, 0)["events"][0]["message"]
            self.assertEqual(decode(received["body"])["reply"]["id"], "source-client-id")
            self.assertEqual(decode(received["body"])["forward"]["sender"], "alice")
            self.assertEqual(api.download_file("bob", bob_token, sent["id"], sent["attachment"]), b"forwarded data")
        finally:
            api.close()


if __name__ == "__main__":
    unittest.main()
