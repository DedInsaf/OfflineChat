import re


USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,19}$")
STATUS_RANK = {"failed": -1, "sending": 0, "sent": 1, "delivered": 2, "read": 3}


def normalize_username(value):
    raw = str(value or "").strip().lstrip("@").lower()
    return "".join(ch for ch in raw if ch.isascii() and (ch.isalnum() or ch == "_"))[:20]


def valid_username(value):
    name = normalize_username(value)
    return name if USERNAME_RE.fullmatch(name) else None


def merge_status(current, incoming):
    current = current or "sending"
    incoming = incoming or "sent"
    return current if STATUS_RANK.get(current, 0) > STATUS_RANK.get(incoming, 0) else incoming


def profile_title(profile, fallback=""):
    profile = profile or {}
    return str(profile.get("display_name") or "").strip() or "@" + str(profile.get("name") or fallback)
