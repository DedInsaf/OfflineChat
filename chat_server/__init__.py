"""Self-hosted OfflineChat server."""

from .database import ChatDatabase, ChatDatabaseError

__all__ = ["ChatDatabase", "ChatDatabaseError"]
