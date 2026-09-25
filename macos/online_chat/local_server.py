import os
import threading
from urllib.parse import urlparse

from chat_server.database import ChatDatabase
from chat_server.server import ChatHTTPServer, ServerState

from .storage import DATA_DIR


_servers = []


def ensure_local_server(server_url):
    """Start the private embedded server when the client targets localhost."""
    parsed = urlparse(str(server_url or ""))
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost"):
        return False
    port = parsed.port or 80
    database_path = os.path.join(DATA_DIR, "server", "offlinechat.sqlite3")
    os.makedirs(os.path.dirname(database_path), exist_ok=True)
    database = ChatDatabase(database_path)
    bind_host = "127.0.0.1" if os.environ.get("OFFLINECHAT_BIND_LAN") == "0" else "0.0.0.0"
    try:
        server = ChatHTTPServer((bind_host, port), ServerState(database))
    except OSError:
        database.close()
        return False
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="Online-Server")
    thread.start()
    _servers.append((server, database, thread))
    return True
