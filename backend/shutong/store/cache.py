"""TTL cache for public metadata API responses (same columns as the legacy api_cache)."""
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Callable, Optional

from .db import Database

_SENSITIVE_KEY_NAMES = frozenset({
    "accesstoken", "apikey", "auth", "authorization", "credential", "credentials",
    "password", "privatekey", "secret", "token",
})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CacheStore:
    def __init__(self, db: Database, clock: Callable[[], datetime] = _utc_now) -> None:
        self.db = db
        self.clock = clock

    def get(self, key: str) -> Optional[Any]:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT response_json, expires_at FROM metadata_cache WHERE cache_key = ?", (key,)
            ).fetchone()
        if row is None or datetime.fromisoformat(row["expires_at"]) <= self.clock():
            return None
        return json.loads(row["response_json"])

    def put(self, key: str, response: Any, ttl_seconds: float) -> None:
        reject_sensitive_keys(response)
        text = json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        now = self.clock()
        with self.db.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO metadata_cache(cache_key, response_json, fetched_at, expires_at)"
                " VALUES (?, ?, ?, ?)",
                (key, text, now.isoformat(), (now + timedelta(seconds=ttl_seconds)).isoformat()),
            )


def reject_sensitive_keys(value: Any) -> None:
    """Refuse to cache anything that looks like it carries a credential."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(key, str) and key.replace("-", "").replace("_", "").casefold() in _SENSITIVE_KEY_NAMES:
                raise ValueError("refusing to cache a response containing {0!r}".format(key))
            reject_sensitive_keys(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            reject_sensitive_keys(nested)
