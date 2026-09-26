import http.client
import base64
import hashlib
from pathlib import Path
import json
import ssl
import threading
from urllib.error import URLError
from urllib.parse import urlparse

try:
    import certifi
except ImportError:
    certifi = None


class OnlineAPIError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class OnlineAPI:
    """Client for the self-hosted OfflineChat HTTP API."""

    def __init__(self, root_url, _legacy_api_key=None):
        parsed = urlparse(str(root_url or "").rstrip("/"))
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Некорректный адрес сервера")
        self.scheme = parsed.scheme
        self.host = parsed.hostname
        self.port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self.base = parsed.path.rstrip("/")
        self.connection = None
        self.lock = threading.Lock()
        self.context = ssl.create_default_context(cafile=certifi.where() if certifi else None)
        if hasattr(ssl, "TLSVersion"):
            self.context.minimum_version = ssl.TLSVersion.TLSv1_2

    def close(self):
        connection, self.connection = self.connection, None
        if connection:
            try:
                connection.close()
            except Exception:
                pass

    def _connect(self, timeout):
        self.close()
        if self.scheme == "https":
            self.connection = http.client.HTTPSConnection(
                self.host, self.port, timeout=timeout, context=self.context
            )
        else:
            self.connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout)

    def request(self, endpoint, payload, timeout=8):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(body)),
            "User-Agent": "OfflineChat-macOS/3.0",
            "Connection": "keep-alive",
        }
        path = self.base + "/v1/" + endpoint.lstrip("/")
        with self.lock:
            last_error = None
            for attempt in range(2):
                try:
                    if self.connection is None:
                        self._connect(timeout)
                    self.connection.timeout = timeout
                    if self.connection.sock:
                        self.connection.sock.settimeout(timeout)
                    self.connection.request("POST", path, body=body, headers=headers)
                    response = self.connection.getresponse()
                    raw = response.read()
                    if response.status >= 400:
                        try:
                            message = json.loads(raw.decode("utf-8")).get("error", "")
                        except Exception:
                            message = raw.decode("utf-8", "replace")
                        raise OnlineAPIError(message or "HTTP %s" % response.status, response.status)
                    try:
                        return json.loads(raw.decode("utf-8")) if raw else None
                    except (UnicodeDecodeError, json.JSONDecodeError) as error:
                        raise OnlineAPIError("Сервер вернул некорректный ответ") from error
                except OnlineAPIError:
                    raise
                except Exception as error:
                    last_error = error
                    self.close()
                    if attempt:
                        raise URLError(str(last_error))
        raise URLError(str(last_error or "request failed"))

    def claim(self, username, display_name, token):
        return self.request("profile/claim", {
            "username": username, "display_name": display_name, "owner_token": token,
        })

    def update_profile(self, username, new_username, display_name, bio, avatar_base64, token):
        return self.request("profile/update", {
            "username": username,
            "new_username": new_username,
            "display_name": display_name,
            "bio": bio,
            "avatar_base64": avatar_base64,
            "owner_token": token,
        }, timeout=20)

    def search(self, query):
        return self.request("profile/search", {"query": query}) or []

    def send(self, sender, recipient, client_id, text, token, attachment=None):
        return self.request("messages/send", {
            "sender": sender,
            "recipient": recipient,
            "client_id": client_id,
            "body": text,
            "owner_token": token,
            "attachment": attachment,
        }, timeout=60 if attachment else 8)

    def send_file(self, sender, recipient, client_id, path, token):
        with open(path, "rb") as stream:
            data = stream.read(5 * 1024 * 1024 + 1)
        if not 0 < len(data) <= 5 * 1024 * 1024:
            raise OnlineAPIError("Выберите непустой файл размером до 5 МБ")
        return self.send(sender, recipient, client_id, "", token, {
            "name": Path(path).name, "data_base64": base64.b64encode(data).decode("ascii"),
        })

    def download_file(self, username, token, message_id, attachment):
        result = self.request("files/download", {
            "username": username, "owner_token": token, "message_id": message_id,
        }, timeout=60)
        data = base64.b64decode(result["data_base64"], validate=True)
        if len(data) != attachment["size"] or hashlib.sha256(data).hexdigest() != attachment["sha256"]:
            raise OnlineAPIError("Файл повреждён при передаче. Повторите скачивание.")
        return data

    def sync(self, username, token, cursor, wait_ms=0):
        return self.request("sync", {
            "username": username,
            "owner_token": token,
            "after_event": int(cursor or 0),
            "wait_ms": int(wait_ms or 0),
        }, timeout=max(8, int(wait_ms / 1000) + 5)) or {}

    def acknowledge(self, username, token, message_ids, status):
        return self.request("messages/ack", {
            "username": username,
            "owner_token": token,
            "message_ids": [int(value) for value in message_ids],
            "status": status,
        })

    def typing(self, username, recipient, token):
        return self.request("typing", {
            "username": username,
            "recipient": recipient,
            "owner_token": token,
        }, timeout=5)
