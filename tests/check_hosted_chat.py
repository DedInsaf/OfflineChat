"""Explicit internet smoke test; creates two isolated synthetic accounts."""
import secrets
import time
import base64
import hashlib
from online_chat.api import OnlineAPI


def main():
    suffix = secrets.token_hex(4)
    names = ["testa_" + suffix, "testb_" + suffix]
    tokens = [secrets.token_hex(32), secrets.token_hex(32)]
    clients = [OnlineAPI("https://dedinsaf.pythonanywhere.com") for _ in names]
    try:
        for client, name, token in zip(clients, names, tokens):
            client.claim(name, "Temporary API test", token)
        start = time.monotonic()
        sent = clients[0].send(names[0], names[1], secrets.token_hex(16), "Synthetic connectivity test", tokens[0])
        received = clients[1].sync(names[1], tokens[1], 0)
        assert any(e.get("message", {}).get("id") == sent["id"] for e in received["events"])
        for status in ("delivered", "read"):
            clients[1].acknowledge(names[1], tokens[1], [sent["id"]], status)
            events = clients[0].sync(names[0], tokens[0], 0)["events"]
            assert any(e.get("message", {}).get("status") == status for e in events)
        reply = clients[1].send(names[1], names[0], secrets.token_hex(16), "Synthetic reply", tokens[1])
        assert any(e.get("message", {}).get("id") == reply["id"]
                   for e in clients[0].sync(names[0], tokens[0], 0)["events"])
        content = b"OfflineChat synthetic attachment\x00\xff"
        for sender, recipient in ((0, 1), (1, 0)):
            file_message = clients[sender].send(names[sender], names[recipient], secrets.token_hex(16), "", tokens[sender],
                {"name": "test-file.bin", "data_base64": base64.b64encode(content).decode()})
            assert file_message.get("attachment", {}).get("sha256") == hashlib.sha256(content).hexdigest()
            downloaded = clients[recipient].download_file(names[recipient], tokens[recipient], file_message["id"], file_message["attachment"])
            assert downloaded == content
            clients[recipient].acknowledge(names[recipient], tokens[recipient], [file_message["id"]], "read")
        print("PASS: bidirectional file upload/download, SHA-256 verification")
        print("PASS: bidirectional messages, delivered, read; %.2f s total" % (time.monotonic() - start))
        print("Synthetic accounts retained: " + ", ".join(names))
    finally:
        for client in clients:
            client.close()


if __name__ == "__main__":
    main()
