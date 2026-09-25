import json
import os
import secrets
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .database import ChatDatabase, ChatDatabaseError


MAX_BODY_BYTES = 1_200_000


class ServerState:
    def __init__(self, database):
        self.database = database
        self.condition = threading.Condition()
        self.generation = 0
        self.typing = {}
        self.admin_token = os.environ.get("OFFLINECHAT_ADMIN_TOKEN", "")

    def notify(self):
        with self.condition:
            self.generation += 1
            self.condition.notify_all()

    def set_typing(self, sender, recipient):
        with self.condition:
            self.typing[(recipient, sender)] = time.monotonic() + 4.0
            self.generation += 1
            self.condition.notify_all()

    def typing_for(self, recipient):
        now = time.monotonic()
        with self.condition:
            expired = [key for key, deadline in self.typing.items() if deadline <= now]
            for key in expired:
                self.typing.pop(key, None)
            return [sender for (target, sender), deadline in self.typing.items() if target == recipient and deadline > now]


class ChatHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "OfflineChat/3"

    @property
    def state(self):
        return self.server.state

    def log_message(self, format_string, *args):
        print("[%s] %s" % (self.log_date_time_string(), format_string % args), flush=True)

    def _json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ChatDatabaseError("invalid content length")
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ChatDatabaseError("invalid request size", 413)
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ChatDatabaseError("invalid JSON")
        if not isinstance(value, dict):
            raise ChatDatabaseError("JSON object required")
        return value

    def _send(self, status, payload):
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            self._send(200, {"ok": True, "database": self.state.database.counts()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        try:
            body = self._json_body()
            if path == "/v1/profile/claim":
                result = self.state.database.claim(
                    body.get("username"), body.get("display_name"), body.get("owner_token")
                )
                self.state.notify()
            elif path == "/v1/profile/update":
                result = self.state.database.update_profile(
                    body.get("username"), body.get("new_username"), body.get("display_name"),
                    body.get("bio"), body.get("avatar_base64"), body.get("owner_token"),
                )
                self.state.notify()
            elif path == "/v1/profile/search":
                result = self.state.database.search(body.get("query"))
            elif path == "/v1/messages/send":
                result, changed = self.state.database.send(
                    body.get("sender"), body.get("recipient"), body.get("client_id"),
                    body.get("body"), body.get("owner_token"),
                )
                if changed:
                    self.state.notify()
            elif path == "/v1/messages/ack":
                result, changed = self.state.database.acknowledge(
                    body.get("username"), body.get("owner_token"), body.get("message_ids"), body.get("status")
                )
                if changed:
                    self.state.notify()
            elif path == "/v1/typing":
                sender = str(body.get("username") or "")
                recipient = str(body.get("recipient") or "")
                self.state.database.sync(sender, body.get("owner_token"), 0)
                self.state.set_typing(sender, recipient)
                result = True
            elif path == "/v1/sync":
                username = str(body.get("username") or "")
                token = body.get("owner_token")
                cursor = body.get("after_event") or 0
                wait_ms = min(25_000, max(0, int(body.get("wait_ms") or 0)))
                with self.state.condition:
                    generation = self.state.generation
                result = self.state.database.sync(username, token, cursor, self.state.typing_for(username))
                if not result["events"] and wait_ms:
                    with self.state.condition:
                        if generation == self.state.generation:
                            self.state.condition.wait(wait_ms / 1000.0)
                    result = self.state.database.sync(username, token, cursor, self.state.typing_for(username))
            elif path == "/v1/admin/reset":
                supplied = self.headers.get("X-Admin-Token", "")
                if not self.state.admin_token or not secrets.compare_digest(supplied, self.state.admin_token):
                    raise ChatDatabaseError("admin access denied", 403)
                self.state.database.reset()
                self.state.notify()
                result = {"ok": True}
            else:
                self._send(404, {"error": "not found"})
                return
            self._send(200, result)
        except ChatDatabaseError as error:
            self._send(error.status, {"error": str(error)})
        except (TypeError, ValueError) as error:
            self._send(400, {"error": str(error) or "invalid request"})
        except Exception as error:
            print("request error: %r" % (error,), flush=True)
            self._send(500, {"error": "internal server error"})


class ChatHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, state):
        self.state = state
        super().__init__(address, ChatHandler)


def main():
    host = os.environ.get("OFFLINECHAT_HOST", "127.0.0.1")
    port = int(os.environ.get("OFFLINECHAT_PORT", "8787"))
    default_data = Path(__file__).resolve().parent / "data"
    data_dir = Path(os.environ.get("OFFLINECHAT_DATA_DIR", str(default_data))).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    database = ChatDatabase(str(data_dir / "offlinechat.sqlite3"))
    server = ChatHTTPServer((host, port), ServerState(database))

    def stop(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("OfflineChat server: http://%s:%s" % (host, port), flush=True)
    print("Database: %s" % database.path, flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        database.close()


if __name__ == "__main__":
    main()
