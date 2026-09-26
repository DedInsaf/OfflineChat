import os
import tempfile
import threading
import unittest

from chat_server.database import ChatDatabase
from chat_server.server import ChatHTTPServer, ServerState
from online_chat.api import OnlineAPI


class ServerHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = ChatDatabase(os.path.join(self.directory.name, "chat.sqlite3"))
        self.server = ChatHTTPServer(("127.0.0.1", 0), ServerState(self.database))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.database.close()
        self.directory.cleanup()

    def test_two_clients_exchange_and_acknowledge_message(self):
        alice = OnlineAPI(self.url)
        bob = OnlineAPI(self.url)
        alice_token = "a" * 64
        bob_token = "b" * 64
        alice.claim("alice", "Alice", alice_token)
        bob.claim("bob", "Bob", bob_token)

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
            api.claim("alice", "Alice", "a" * 64)
            api.claim("bob", "Bob", "b" * 64)
            message = api.send_file("alice", "bob", "file-http", path, "a" * 64)
            self.assertEqual(api.download_file("bob", "b" * 64, message["id"], message["attachment"]), path.read_bytes())
        finally:
            api.close()


if __name__ == "__main__":
    unittest.main()
