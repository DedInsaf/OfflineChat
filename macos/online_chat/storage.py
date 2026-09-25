import json
import os
import tempfile
import uuid

from .models import valid_username


DATA_DIR = os.path.expanduser("~/Library/Application Support/OfflineChat")
CHATS_PATH = os.path.join(DATA_DIR, "online_chats_v3.json")
USER_PATH = os.path.join(DATA_DIR, "online_user_v3.json")
SYNC_PATH = os.path.join(DATA_DIR, "online_sync_v3.json")
PROFILES_PATH = os.path.join(DATA_DIR, "online_profiles_v3.json")
CREDENTIAL_PATH = os.path.join(DATA_DIR, ".online_credentials_v3.json")
SETTINGS_PATH = os.path.join(DATA_DIR, "online_server.json")
DEFAULT_SERVER_URL = "https://dedinsaf.pythonanywhere.com"
LEGACY_PLACEHOLDERS = {"Избранное", "Команда"}


def _atomic_write(path, value, mode=0o600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".offlinechat-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return fallback


def _safe_write(path, value, mode=0o600):
    try:
        _atomic_write(path, value, mode=mode)
        return True
    except OSError:
        return False


def load_chats():
    value = _load(CHATS_PATH, {})
    if not isinstance(value, dict):
        return {}
    return {
        str(peer): history for peer, history in value.items()
        if isinstance(history, list) and peer not in LEGACY_PLACEHOLDERS
    }


def save_chats(value):
    _safe_write(CHATS_PATH, value)


def load_profiles():
    value = _load(PROFILES_PATH, {})
    return value if isinstance(value, dict) else {}


def save_profiles(value):
    _safe_write(PROFILES_PATH, value)


def load_username():
    value = _load(USER_PATH, {})
    return valid_username(value.get("username")) if isinstance(value, dict) else ""


def save_username(value):
    _safe_write(USER_PATH, {"username": valid_username(value) or ""})


def load_owner_token():
    value = _load(CREDENTIAL_PATH, {})
    token = value.get("owner_token") if isinstance(value, dict) else None
    if isinstance(token, str) and len(token) >= 32:
        return token
    token = str(uuid.uuid4()) + str(uuid.uuid4())
    _safe_write(CREDENTIAL_PATH, {"owner_token": token}, mode=0o600)
    return token


def load_cursor(username):
    value = _load(SYNC_PATH, {})
    if not isinstance(value, dict) or value.get("username") != username:
        return 0
    try:
        return max(0, int(value.get("cursor") or 0))
    except (TypeError, ValueError):
        return 0


def save_cursor(username, cursor):
    _safe_write(SYNC_PATH, {"username": username, "cursor": int(cursor or 0)})


def load_server_url():
    value = _load(SETTINGS_PATH, {})
    configured = value.get("url") if isinstance(value, dict) else None
    environment = os.environ.get("OFFLINECHAT_SERVER_URL")
    return str(environment or configured or DEFAULT_SERVER_URL).rstrip("/")


def save_server_url(value):
    url = str(value or "").strip().rstrip("/")
    if url.startswith("http://") or url.startswith("https://"):
        return _safe_write(SETTINGS_PATH, {"url": url})
    return False
