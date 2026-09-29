import hashlib
import hmac
import base64
import binascii
import json
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone


USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,19}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
STATUS_RANK = {"sent": 1, "delivered": 2, "read": 3}
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENT_STORAGE = 100 * 1024 * 1024


class ChatDatabaseError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _username(value):
    name = str(value or "").strip().lstrip("@").lower()
    if not USERNAME_RE.fullmatch(name):
        raise ChatDatabaseError("invalid username")
    return name


def _token_hash(token):
    value = str(token or "")
    if len(value) < 32:
        raise ChatDatabaseError("invalid owner token", 401)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _email(value):
    address = str(value or "").strip().lower()
    if len(address) > 254 or not EMAIL_RE.fullmatch(address):
        raise ChatDatabaseError("invalid email address")
    return address


def _password(value):
    password = str(value or "")
    if len(password) < 10 or len(password) > 128:
        raise ChatDatabaseError("password must contain 10 to 128 characters")
    if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
        raise ChatDatabaseError("password must contain letters and numbers")
    return password


def _password_digest(password, salt, iterations=310_000):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


class ChatDatabase:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.connection.row_factory = sqlite3.Row
        with self.lock:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=NORMAL")
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    name TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    bio TEXT NOT NULL DEFAULT '',
                    avatar_base64 TEXT,
                    owner_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('sent', 'delivered', 'read')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(sender, client_id),
                    FOREIGN KEY(sender) REFERENCES profiles(name) ON UPDATE CASCADE,
                    FOREIGN KEY(recipient) REFERENCES profiles(name) ON UPDATE CASCADE
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    message_id INTEGER,
                    peer_name TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS events_user_cursor ON events(username, id);
                CREATE INDEX IF NOT EXISTS messages_sender ON messages(sender, id);
                CREATE INDEX IF NOT EXISTS messages_recipient ON messages(recipient, id);
                CREATE TABLE IF NOT EXISTS attachments (
                    message_id INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
                    content BLOB NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_accounts (
                    username TEXT PRIMARY KEY REFERENCES profiles(name) ON UPDATE CASCADE ON DELETE CASCADE,
                    email TEXT NOT NULL UNIQUE,
                    password_salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    password_iterations INTEGER NOT NULL,
                    verified_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_challenges (
                    id TEXT PRIMARY KEY,
                    purpose TEXT NOT NULL CHECK(purpose IN ('register', 'login')),
                    username TEXT NOT NULL,
                    email TEXT NOT NULL,
                    display_name TEXT,
                    password_salt BLOB,
                    password_hash BLOB,
                    password_iterations INTEGER,
                    code_hash TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS auth_challenges_expiry ON auth_challenges(expires_at);
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL REFERENCES profiles(name) ON UPDATE CASCADE ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions(username);
                CREATE TABLE IF NOT EXISTS auth_login_attempts (
                    identity TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL,
                    blocked_until INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                """
            )
            columns = {row[1] for row in self.connection.execute("PRAGMA table_info(messages)")}
            if "attachment" not in columns:
                self.connection.execute("ALTER TABLE messages ADD COLUMN attachment TEXT")
            self.connection.commit()

    def close(self):
        with self.lock:
            self.connection.close()

    @staticmethod
    def _profile(row):
        return {
            "name": row["name"],
            "display_name": row["display_name"],
            "bio": row["bio"],
            "avatar_base64": row["avatar_base64"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _message(row):
        return {
            "id": int(row["id"]),
            "client_id": row["client_id"],
            "attachment": json.loads(row["attachment"]) if row["attachment"] else None,
            "sender": row["sender"],
            "recipient": row["recipient"],
            "body": row["body"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _owned_profile(self, username, owner_token):
        row = self._authenticated_profile(owner_token)
        if row["name"] != _username(username):
            raise ChatDatabaseError("session does not belong to this account", 403)
        return row

    def _authenticated_profile(self, session_token):
        token_hash = _token_hash(session_token)
        now = int(time.time())
        row = self.connection.execute(
            "SELECT p.* FROM auth_sessions s JOIN profiles p ON p.name = s.username "
            "WHERE s.token_hash = ? AND s.expires_at > ?", (token_hash, now)
        ).fetchone()
        if row is None:
            raise ChatDatabaseError("session expired or invalid", 401)
        return row

    @staticmethod
    def _challenge_hash(challenge_id, code):
        return hashlib.sha256((challenge_id + ":" + str(code)).encode("utf-8")).hexdigest()

    def _new_session(self, username):
        token = secrets.token_urlsafe(48)
        now = int(time.time())
        self.connection.execute(
            "INSERT INTO auth_sessions(token_hash, username, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (_token_hash(token), username, now + 30 * 24 * 60 * 60, now),
        )
        return token

    def _clear_expired_auth(self):
        now = int(time.time())
        self.connection.execute("DELETE FROM auth_challenges WHERE expires_at <= ?", (now,))
        self.connection.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,))
        self.connection.commit()

    def start_registration(self, username, email, password, password_confirmation, display_name=None):
        name = _username(username)
        address = _email(email)
        secret = _password(password)
        if secret != str(password_confirmation or ""):
            raise ChatDatabaseError("passwords do not match")
        title = str(display_name or "").strip()[:80] or name
        salt = secrets.token_bytes(16)
        iterations = 310_000
        digest = _password_digest(secret, salt, iterations)
        challenge_id = secrets.token_urlsafe(32)
        code = "%06d" % secrets.randbelow(1_000_000)
        now = int(time.time())
        with self.lock:
            self._clear_expired_auth()
            if self.connection.execute("SELECT 1 FROM profiles WHERE name = ?", (name,)).fetchone():
                raise ChatDatabaseError("username is already taken", 409)
            if self.connection.execute("SELECT 1 FROM auth_accounts WHERE email = ?", (address,)).fetchone():
                raise ChatDatabaseError("email is already registered", 409)
            recent = self.connection.execute(
                "SELECT created_at FROM auth_challenges WHERE username = ? OR email = ? ORDER BY created_at DESC LIMIT 1",
                (name, address),
            ).fetchone()
            if recent is not None and int(recent["created_at"]) > now - 60:
                raise ChatDatabaseError("wait before requesting another code", 429)
            self.connection.execute("DELETE FROM auth_challenges WHERE username = ? OR email = ?", (name, address))
            self.connection.execute(
                "INSERT INTO auth_challenges(id, purpose, username, email, display_name, password_salt, "
                "password_hash, password_iterations, code_hash, expires_at, created_at) "
                "VALUES (?, 'register', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (challenge_id, name, address, title, salt, digest, iterations,
                 self._challenge_hash(challenge_id, code), now + 600, now),
            )
            self.connection.commit()
        return {"challenge_id": challenge_id, "email_hint": self._email_hint(address), "expires_in": 600}, address, code

    def start_login(self, identifier, password):
        identity = str(identifier or "").strip().lower().lstrip("@")
        secret = str(password or "")
        with self.lock:
            self._clear_expired_auth()
            attempt = self.connection.execute(
                "SELECT * FROM auth_login_attempts WHERE identity = ?", (identity,)
            ).fetchone()
            if attempt is not None and int(attempt["blocked_until"]) > int(time.time()):
                raise ChatDatabaseError("too many login attempts; try again later", 429)
            row = self.connection.execute(
                "SELECT a.*, p.display_name FROM auth_accounts a JOIN profiles p ON p.name = a.username "
                "WHERE a.username = ? OR a.email = ?", (identity, identity)
            ).fetchone()
            if row is None:
                self._record_login_failure(identity)
                raise ChatDatabaseError("invalid username/email or password", 401)
            actual = _password_digest(secret, row["password_salt"], int(row["password_iterations"]))
            if not hmac.compare_digest(actual, row["password_hash"]):
                self._record_login_failure(identity)
                raise ChatDatabaseError("invalid username/email or password", 401)
            self.connection.execute("DELETE FROM auth_login_attempts WHERE identity IN (?, ?, ?)",
                                    (identity, row["username"], row["email"]))
            recent = self.connection.execute(
                "SELECT created_at FROM auth_challenges WHERE username = ? ORDER BY created_at DESC LIMIT 1",
                (row["username"],),
            ).fetchone()
            if recent is not None and int(recent["created_at"]) > int(time.time()) - 60:
                self.connection.commit()
                raise ChatDatabaseError("wait before requesting another code", 429)
            challenge_id = secrets.token_urlsafe(32)
            code = "%06d" % secrets.randbelow(1_000_000)
            now = int(time.time())
            self.connection.execute("DELETE FROM auth_challenges WHERE username = ?", (row["username"],))
            self.connection.execute(
                "INSERT INTO auth_challenges(id, purpose, username, email, display_name, code_hash, expires_at, created_at) "
                "VALUES (?, 'login', ?, ?, ?, ?, ?, ?)",
                (challenge_id, row["username"], row["email"], row["display_name"],
                 self._challenge_hash(challenge_id, code), now + 600, now),
            )
            self.connection.commit()
        return {"challenge_id": challenge_id, "email_hint": self._email_hint(row["email"]), "expires_in": 600}, row["email"], code

    def _record_login_failure(self, identity):
        now = int(time.time())
        row = self.connection.execute("SELECT failures, updated_at FROM auth_login_attempts WHERE identity = ?",
                                      (identity,)).fetchone()
        failures = 1 if row is None or int(row["updated_at"]) < now - 900 else int(row["failures"]) + 1
        blocked_until = now + 900 if failures >= 5 else 0
        self.connection.execute(
            "INSERT INTO auth_login_attempts(identity, failures, blocked_until, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(identity) DO UPDATE SET failures=excluded.failures, "
            "blocked_until=excluded.blocked_until, updated_at=excluded.updated_at",
            (identity, failures, blocked_until, now),
        )
        self.connection.commit()

    @staticmethod
    def _email_hint(address):
        local, domain = address.split("@", 1)
        return (local[:2] + "***" if len(local) > 2 else local[:1] + "***") + "@" + domain

    def cancel_challenge(self, challenge_id):
        with self.lock:
            self.connection.execute("DELETE FROM auth_challenges WHERE id = ?", (str(challenge_id or ""),))
            self.connection.commit()

    def verify_challenge(self, challenge_id, code, purpose):
        identifier = str(challenge_id or "")
        supplied = str(code or "").strip()
        if len(identifier) < 20 or not re.fullmatch(r"\d{6}", supplied):
            raise ChatDatabaseError("invalid verification code")
        with self.lock:
            self._clear_expired_auth()
            row = self.connection.execute("SELECT * FROM auth_challenges WHERE id = ? AND purpose = ?",
                                          (identifier, purpose)).fetchone()
            if row is None:
                raise ChatDatabaseError("verification code expired; request a new code", 401)
            if int(row["attempts"]) >= 5:
                self.connection.execute("DELETE FROM auth_challenges WHERE id = ?", (identifier,))
                self.connection.commit()
                raise ChatDatabaseError("too many code attempts; request a new code", 429)
            if not hmac.compare_digest(row["code_hash"], self._challenge_hash(identifier, supplied)):
                self.connection.execute("UPDATE auth_challenges SET attempts = attempts + 1 WHERE id = ?", (identifier,))
                self.connection.commit()
                raise ChatDatabaseError("invalid verification code", 401)
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                if purpose == "register":
                    now_iso = _now_iso()
                    self.connection.execute(
                        "INSERT INTO profiles(name, display_name, owner_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                        (row["username"], row["display_name"] or row["username"], "password-auth-disabled-legacy", now_iso, now_iso),
                    )
                    self.connection.execute(
                        "INSERT INTO auth_accounts(username, email, password_salt, password_hash, password_iterations, verified_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (row["username"], row["email"], row["password_salt"], row["password_hash"],
                         row["password_iterations"], now_iso),
                    )
                token = self._new_session(row["username"])
                self.connection.execute("DELETE FROM auth_challenges WHERE id = ?", (identifier,))
                self.connection.commit()
            except sqlite3.IntegrityError:
                self.connection.rollback()
                raise ChatDatabaseError("account is already registered", 409)
            except Exception:
                self.connection.rollback()
                raise
            profile = self.connection.execute("SELECT * FROM profiles WHERE name = ?", (row["username"],)).fetchone()
            return {"session_token": token, "profile": self._profile(profile)}

    def logout(self, session_token):
        token_hash = _token_hash(session_token)
        with self.lock:
            self.connection.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))
            self.connection.commit()
        return {"ok": True}

    def _add_message_events(self, message_id, sender, recipient, kind="message"):
        now = _now_iso()
        self.connection.executemany(
            "INSERT INTO events(username, kind, message_id, peer_name, created_at) VALUES (?, ?, ?, ?, ?)",
            ((sender, kind, message_id, recipient, now), (recipient, kind, message_id, sender, now)),
        )

    def claim(self, username, display_name, owner_token):
        raise ChatDatabaseError("old sign-in method is disabled; update the app", 410)

    def update_profile(self, username, new_username, display_name, bio, avatar_base64, owner_token):
        old_name = _username(username)
        new_name = _username(new_username)
        title = str(display_name or "").strip()[:80] or new_name
        about = str(bio or "").strip()[:160]
        avatar = avatar_base64 if isinstance(avatar_base64, str) and len(avatar_base64) <= 800_000 else None
        now = _now_iso()
        with self.lock:
            self._owned_profile(old_name, owner_token)
            if new_name != old_name:
                taken = self.connection.execute("SELECT 1 FROM profiles WHERE name = ?", (new_name,)).fetchone()
                if taken:
                    raise ChatDatabaseError("username is already taken", 409)
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                if new_name != old_name:
                    self.connection.execute("UPDATE profiles SET name = ? WHERE name = ?", (new_name, old_name))
                    self.connection.execute("UPDATE events SET username = ? WHERE username = ?", (new_name, old_name))
                    self.connection.execute("UPDATE events SET peer_name = ? WHERE peer_name = ?", (new_name, old_name))
                self.connection.execute(
                    "UPDATE profiles SET display_name = ?, bio = ?, avatar_base64 = ?, updated_at = ? WHERE name = ?",
                    (title, about, avatar, now, new_name),
                )
                peers = self.connection.execute(
                    "SELECT DISTINCT CASE WHEN sender = ? THEN recipient ELSE sender END AS peer "
                    "FROM messages WHERE sender = ? OR recipient = ?",
                    (new_name, new_name, new_name),
                ).fetchall()
                for peer in peers:
                    peer_name = peer["peer"]
                    if not peer_name:
                        continue
                    self.connection.execute(
                        "INSERT INTO events(username, kind, peer_name, created_at) VALUES (?, 'profile', ?, ?)",
                        (peer_name, new_name, now),
                    )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            row = self.connection.execute("SELECT * FROM profiles WHERE name = ?", (new_name,)).fetchone()
            return self._profile(row)

    def search(self, query):
        raw = str(query or "").strip().lstrip("@").lower()[:20]
        if len(raw) < 2 or any(not (char.isascii() and (char.isalnum() or char == "_")) for char in raw):
            return []
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM profiles WHERE name LIKE ? ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END, name LIMIT 20",
                (raw + "%", raw),
            ).fetchall()
            return [self._profile(row) for row in rows]

    def send(self, sender, recipient, client_id, body, owner_token, attachment=None):
        from_name = _username(sender)
        to_name = _username(recipient)
        text = str(body or "").strip()
        request_id = str(client_id or "").strip()
        if from_name == to_name:
            raise ChatDatabaseError("cannot send a message to yourself")
        if not request_id or len(request_id) > 80:
            raise ChatDatabaseError("invalid client id")
        if (not text and attachment is None) or len(text) > 4000:
            raise ChatDatabaseError("message must contain 1 to 4000 characters")
        now = _now_iso()
        with self.lock:
            self._owned_profile(from_name, owner_token)
            if self.connection.execute("SELECT 1 FROM profiles WHERE name = ?", (to_name,)).fetchone() is None:
                raise ChatDatabaseError("recipient not found", 404)
            existing = self.connection.execute(
                "SELECT * FROM messages WHERE sender = ? AND client_id = ?", (from_name, request_id)
            ).fetchone()
            if existing is not None:
                return self._message(existing), False
            metadata, content = None, None
            if attachment is not None:
                if not isinstance(attachment, dict):
                    raise ChatDatabaseError("invalid attachment")
                filename = attachment.get("name")
                encoded = attachment.get("data_base64")
                if (not isinstance(filename, str) or not filename.strip() or len(filename) > 180
                        or filename in (".", "..") or any(c in filename for c in "/\\")
                        or any(ord(c) < 32 or ord(c) == 127 for c in filename)):
                    raise ChatDatabaseError("invalid filename")
                if not isinstance(encoded, str) or len(encoded) > ((MAX_FILE_BYTES + 2) // 3) * 4:
                    raise ChatDatabaseError("file exceeds 5 MB", 413)
                try:
                    content = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    raise ChatDatabaseError("invalid file encoding")
                if not 0 < len(content) <= MAX_FILE_BYTES:
                    raise ChatDatabaseError("file must contain 1 byte to 5 MB", 413)
                metadata = json.dumps({"name": filename, "size": len(content),
                                       "sha256": hashlib.sha256(content).hexdigest()}, ensure_ascii=False)
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                if content is not None:
                    used = self.connection.execute("SELECT COALESCE(SUM(length(content)), 0) FROM attachments").fetchone()[0]
                    if used + len(content) > MAX_ATTACHMENT_STORAGE:
                        raise ChatDatabaseError("file storage is full", 507)
                cursor = self.connection.execute(
                    "INSERT INTO messages(client_id, sender, recipient, body, status, created_at, updated_at, attachment) "
                    "VALUES (?, ?, ?, ?, 'sent', ?, ?, ?)",
                    (request_id, from_name, to_name, text, now, now, metadata),
                )
                if content is not None:
                    self.connection.execute("INSERT INTO attachments(message_id, content) VALUES (?, ?)",
                                            (cursor.lastrowid, content))
                self._add_message_events(cursor.lastrowid, from_name, to_name)
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            row = self.connection.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return self._message(row), True

    def download(self, username, owner_token, message_id):
        with self.lock:
            profile = self._owned_profile(username, owner_token)
            row = self.connection.execute(
                "SELECT a.content FROM attachments a JOIN messages m ON m.id = a.message_id "
                "WHERE m.id = ? AND (m.sender = ? OR m.recipient = ?)",
                (int(message_id), profile["name"], profile["name"]),
            ).fetchone()
            if row is None:
                raise ChatDatabaseError("file not found", 404)
            return {"data_base64": base64.b64encode(row["content"]).decode("ascii")}

    def acknowledge(self, username, owner_token, message_ids, status):
        name = _username(username)
        target_status = str(status or "")
        if target_status not in ("delivered", "read"):
            raise ChatDatabaseError("invalid receipt status")
        ids = sorted({int(value) for value in (message_ids or []) if str(value).isdigit()})
        if not ids:
            return [], False
        changed = []
        with self.lock:
            self._owned_profile(name, owner_token)
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                for message_id in ids:
                    row = self.connection.execute(
                        "SELECT * FROM messages WHERE id = ? AND recipient = ?", (message_id, name)
                    ).fetchone()
                    if row is None or STATUS_RANK[row["status"]] >= STATUS_RANK[target_status]:
                        continue
                    now = _now_iso()
                    self.connection.execute(
                        "UPDATE messages SET status = ?, updated_at = ? WHERE id = ?",
                        (target_status, now, message_id),
                    )
                    self._add_message_events(message_id, row["sender"], row["recipient"], "receipt")
                    changed.append(message_id)
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
        return changed, bool(changed)

    def sync(self, username, owner_token, after_event, typing_senders=()):
        name = _username(username)
        cursor = max(0, int(after_event or 0))
        with self.lock:
            self._owned_profile(name, owner_token)
            rows = self.connection.execute(
                "SELECT e.id AS event_id, e.kind, m.* FROM events e "
                "LEFT JOIN messages m ON m.id = e.message_id "
                "WHERE e.username = ? AND (e.id > ? OR (m.recipient = ? AND m.status = 'sent')) "
                "ORDER BY e.id LIMIT 500",
                (name, cursor, name),
            ).fetchall()
            events = []
            next_cursor = cursor
            for row in rows:
                next_cursor = max(next_cursor, int(row["event_id"]))
                if row["id"] is not None:
                    events.append({
                        "event_id": int(row["event_id"]),
                        "kind": row["kind"],
                        "message": self._message(row),
                    })
            peer_rows = self.connection.execute(
                "SELECT DISTINCT CASE WHEN sender = ? THEN recipient ELSE sender END AS peer "
                "FROM messages WHERE sender = ? OR recipient = ?",
                (name, name, name),
            ).fetchall()
            profile_names = {name}
            profile_names.update(row["peer"] for row in peer_rows if row["peer"])
            profiles = []
            if profile_names:
                placeholders = ",".join("?" for _ in profile_names)
                profiles = [self._profile(row) for row in self.connection.execute(
                    "SELECT * FROM profiles WHERE name IN (" + placeholders + ")", tuple(profile_names)
                ).fetchall()]
            return {
                "cursor": next_cursor,
                "events": events,
                "profiles": profiles,
                "typing": sorted(set(typing_senders)),
            }

    def reset(self):
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute("DELETE FROM events")
            self.connection.execute("DELETE FROM messages")
            self.connection.execute("DELETE FROM auth_challenges")
            self.connection.execute("DELETE FROM auth_sessions")
            self.connection.execute("DELETE FROM auth_accounts")
            self.connection.execute("DELETE FROM auth_login_attempts")
            self.connection.execute("DELETE FROM profiles")
            self.connection.execute("DELETE FROM sqlite_sequence")
            self.connection.commit()

    def counts(self):
        with self.lock:
            return {
                table: int(self.connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0])
                for table in ("profiles", "messages", "events", "auth_accounts", "auth_sessions")
            }
