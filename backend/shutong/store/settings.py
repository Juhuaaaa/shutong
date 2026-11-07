"""Key/value settings stored as JSON; secrets are never echoed back."""
import json
from typing import Any, Dict

from .db import Database

SECRET_KEYS = frozenset({"bangumi.token", "ai.api_key", "auth.password_hash", "auth.session_secret"})

DEFAULTS: Dict[str, Any] = {
    "bangumi.base_url": "https://api.bgm.tv",
    "bangumi.token": None,
    "metadata.sources": ["bangumi"],
    "network.proxy": "",
    "ai.base_url": "",
    "ai.api_key": "",
    "ai.model": "",
    "ai.threshold": 0.85,
    "ai.use_proxy": False,
    "log.level": "INFO",
}

_UNSET = object()


class SettingsStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, default: Any = _UNSET) -> Any:
        with self.db.connect() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is not None:
            return json.loads(row["value"])
        if default is not _UNSET:
            return default
        return DEFAULTS.get(key)

    def set(self, key: str, value: Any) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False, allow_nan=False)),
            )

    def delete(self, key: str) -> None:
        with self.db.connect() as connection:
            connection.execute("DELETE FROM settings WHERE key = ?", (key,))

    def public(self) -> Dict[str, Any]:
        """Every setting with defaults filled in; secrets become "已设置" or ""."""
        values = dict(DEFAULTS)
        with self.db.connect() as connection:
            for row in connection.execute("SELECT key, value FROM settings"):
                values[row["key"]] = json.loads(row["value"])
        for key in SECRET_KEYS:
            values[key] = "已设置" if values.get(key) else ""
        return values
