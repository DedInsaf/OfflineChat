import queue
import time

from .api import OnlineAPI
from .models import valid_username
from .storage import load_cursor, load_owner_token, save_cursor


def _error_text(error):
    value = str(error or "")
    lowered = value.lower()
    if "username is already taken" in lowered:
        return "Этот @username уже занят"
    if "invalid owner token" in lowered:
        return "Профиль принадлежит другому устройству"
    if "connection refused" in lowered:
        return "Личный сервер не запущен"
    return value or "Сервер временно недоступен"


def online_worker(status_queue, command_queue, display_name, server_url, api_key):
    if not server_url:
        while True:
            command = command_queue.get()
            if command.get("type") == "shutdown":
                return
            status_queue.put({"event": "online_network_error", "message": "Адрес общего сервера ещё не настроен"})
    api = OnlineAPI(server_url, api_key)
    token = load_owner_token()
    username = valid_username(display_name) or ""
    cursor = load_cursor(username) if username else 0
    claimed = False
    last_poll = 0.0
    last_error = 0.0
    connected = False
    profile_signatures = {}
    typing_state = set()
    pending_deliveries = set()
    pending_reads = {}

    def emit(event, **payload):
        status_queue.put({"event": event, **payload})

    def network_error(error):
        nonlocal last_error, connected
        connected = False
        now = time.monotonic()
        if now - last_error >= 8:
            last_error = now
            emit("online_network_error", message=_error_text(error))

    def ensure_claimed():
        nonlocal claimed
        if not username or claimed:
            return claimed
        profile = api.claim(username, username, token)
        claimed = True
        profile_signatures[username] = tuple(profile.get(key) for key in ("display_name", "bio", "avatar_base64"))
        emit("online_profile", profile=profile, mine=True)
        return True

    def handle(command):
        nonlocal username, cursor, claimed
        kind = command.get("type")
        if kind == "shutdown":
            return False
        if kind == "set_username":
            username = valid_username(command.get("name")) or ""
            cursor = 0 if command.get("reset_cursor") else (load_cursor(username) if username else 0)
            if username and command.get("reset_cursor"):
                save_cursor(username, 0)
            claimed = False
            if username:
                ensure_claimed()
            return True
        if kind == "claim_username":
            wanted = valid_username(command.get("name"))
            if not wanted:
                emit("online_username_error", message="От 3 до 20 символов: латиница, цифры и _. Первый символ — буква.")
                return True
            try:
                profile = api.claim(wanted, command.get("display_name") or wanted, token)
                username, cursor, claimed = wanted, 0, True
                profile_signatures[username] = tuple(profile.get(key) for key in ("display_name", "bio", "avatar_base64"))
                save_cursor(username, 0)
                emit("online_username_ok", name=username, profile=profile, message="Ваш юз @" + username)
            except Exception as exc:
                emit("online_username_error", message=_error_text(exc))
            return True
        if not username:
            return True
        if kind == "find_user":
            query = valid_username(command.get("name"))
            if not query:
                emit("online_find", found=False, name=command.get("name", ""), message="Некорректный @username")
                return True
            try:
                profiles = api.search(query)
                profile = next((item for item in profiles if item.get("name") == query), None)
                emit("online_find", found=profile is not None, name=query, profile=profile,
                     message="Пользователь не найден" if profile is None else "")
            except Exception as exc:
                emit("online_find", found=False, name=query, message=_error_text(exc))
            return True
        if kind == "online_send":
            try:
                message = api.send(username, command.get("recipient"), command.get("local_id"), command.get("text"), token)
                emit("online_message_sync", message=message, source="send")
            except Exception as exc:
                emit("online_send_failed", recipient=command.get("recipient"), local_id=command.get("local_id"), message=_error_text(exc))
            return True
        if kind == "online_typing":
            try:
                api.typing(username, command.get("recipient"), token)
            except Exception:
                pass
            return True
        if kind == "online_read":
            ids = command.get("message_ids") or []
            for message_id in ids:
                try:
                    pending_reads[int(message_id)] = command.get("peer")
                except (TypeError, ValueError):
                    pass
            return True
        if kind == "update_online_profile":
            new_name = valid_username(command.get("username"))
            if not new_name:
                emit("online_profile_error", message="Некорректный @username")
                return True
            try:
                profile = api.update_profile(
                    username, new_name, command.get("display_name") or "", command.get("bio") or "",
                    command.get("avatar_base64"), token,
                )
                old_name = username
                username, claimed = new_name, True
                profile_signatures.pop(old_name, None)
                profile_signatures[username] = tuple(profile.get(key) for key in ("display_name", "bio", "avatar_base64"))
                if old_name != new_name:
                    cursor = 0
                    save_cursor(username, 0)
                emit("online_profile_updated", name=username, old_name=old_name, profile=profile)
            except Exception as exc:
                emit("online_profile_error", message=_error_text(exc))
            return True
        return True

    try:
        while True:
            handled = False
            while True:
                try:
                    command = command_queue.get_nowait()
                except queue.Empty:
                    break
                handled = True
                try:
                    if not handle(command):
                        return
                except Exception as exc:
                    network_error(exc)

            now = time.monotonic()
            if username and now - last_poll >= 1.0:
                last_poll = now
                try:
                    ensure_claimed()
                    response = api.sync(username, token, cursor)
                    for profile in response.get("profiles") or []:
                        profile_name = profile.get("name")
                        signature = tuple(profile.get(key) for key in ("display_name", "bio", "avatar_base64"))
                        if profile_name and profile_signatures.get(profile_name) != signature:
                            profile_signatures[profile_name] = signature
                            emit("online_profile", profile=profile, mine=profile_name == username)
                    new_typing = set(response.get("typing") or [])
                    if new_typing != typing_state:
                        typing_state = new_typing
                        emit("online_typing_state", senders=list(new_typing))
                    for event in response.get("events") or []:
                        message = event.get("message") or {}
                        emit("online_message_sync", message=message, source="sync", event_id=event.get("event_id"))
                        if message.get("recipient") == username and message.get("status") == "sent" and message.get("id"):
                            pending_deliveries.add(int(message["id"]))
                    cursor = max(cursor, int(response.get("cursor") or cursor))
                    save_cursor(username, cursor)
                    if pending_deliveries:
                        api.acknowledge(username, token, list(pending_deliveries), "delivered")
                        pending_deliveries.clear()
                    if pending_reads:
                        read_snapshot = dict(pending_reads)
                        api.acknowledge(username, token, list(read_snapshot), "read")
                        pending_reads.clear()
                        peers = set(read_snapshot.values())
                        for peer in peers:
                            emit("online_local_read", peer=peer,
                                 message_ids=[mid for mid, value in read_snapshot.items() if value == peer])
                    if not connected:
                        connected = True
                        emit("online_connected", message="Онлайн")
                except Exception as exc:
                    network_error(exc)
            time.sleep(0.04 if handled else 0.12)
    finally:
        api.close()
