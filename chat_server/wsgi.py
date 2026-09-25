"""WSGI entry point for shared hosting with a single web worker.

Reuse the HTTP API dispatch without opening a listening socket. Long polling
is disabled here so one waiting client cannot block another client's send.
"""
import json
import os
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

from .database import ChatDatabase, ChatDatabaseError
from .server import ChatHandler, MAX_BODY_BYTES, ServerState


class WSGIHandler(ChatHandler):
    def __init__(self, state, path, body):
        self.server = SimpleNamespace(state=state)
        self.path = path
        self.body = body
        self.headers = {}
        self.response = None

    def _json_body(self):
        return self.body

    def _send(self, status, payload):
        self.response = status, payload


def create_application(database_path):
    state = ServerState(ChatDatabase(str(database_path)))

    def application(environ, start_response):
        try:
            path = environ.get("PATH_INFO", "").rstrip("/")
            method = environ.get("REQUEST_METHOD", "GET")
            if path == "/health" and method == "GET":
                status, payload = 200, {"ok": True, "transport": "polling"}
            elif path.startswith("/v1/admin/"):
                status, payload = 404, {"error": "not found"}
            elif method != "POST":
                status, payload = 405, {"error": "POST required"}
            else:
                length = int(environ.get("CONTENT_LENGTH") or "0")
                if not 0 < length <= MAX_BODY_BYTES:
                    raise ChatDatabaseError("invalid request size", 413)
                raw = environ["wsgi.input"].read(length)
                if len(raw) != length:
                    raise ChatDatabaseError("incomplete request")
                body = json.loads(raw.decode("utf-8"))
                if not isinstance(body, dict):
                    raise ChatDatabaseError("JSON object required")
                body["wait_ms"] = 0
                handler = WSGIHandler(state, path, body)
                handler.do_POST()
                status, payload = handler.response
        except ChatDatabaseError as error:
            status, payload = error.status, {"error": str(error)}
        except (ValueError, TypeError, UnicodeDecodeError):
            status, payload = 400, {"error": "invalid request"}
        except Exception:
            status, payload = 500, {"error": "internal server error"}
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        start_response(f"{status} {HTTPStatus(status).phrase}", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(encoded))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
        ])
        return [encoded]

    application.database = state.database
    return application


def hosted_application():
    directory = Path(os.environ.get("OFFLINECHAT_DATA_DIR", str(Path.home() / "offlinechat-data")))
    directory.mkdir(parents=True, exist_ok=True)
    return create_application(directory / "offlinechat.sqlite3")
