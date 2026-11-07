from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from shutong.store.cache import CacheStore
from shutong.store.db import Database


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 29, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class CacheStoreTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        db = Database(Path(self._directory.name) / "shutong.db")
        db.migrate()
        self.clock = Clock()
        self.cache = CacheStore(db, clock=self.clock)

    def test_put_get_and_expiry(self):
        self.cache.put("bangumi:subject:1", {"id": 1, "name": "迷宫饭"}, ttl_seconds=1)
        self.assertEqual(self.cache.get("bangumi:subject:1"), {"id": 1, "name": "迷宫饭"})
        self.clock.now += timedelta(seconds=2)
        self.assertIsNone(self.cache.get("bangumi:subject:1"))
        self.assertIsNone(self.cache.get("missing"))

    def test_overwrite_same_key(self):
        self.cache.put("k", [1], ttl_seconds=60)
        self.cache.put("k", [2], ttl_seconds=60)
        self.assertEqual(self.cache.get("k"), [2])

    def test_rejects_sensitive_keys_nested(self):
        for payload in ({"data": [{"Access-Token": "x"}]}, {"api_key": "x"}, {"AUTHORIZATION": "x"},
                        [{"private_key": "x"}]):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.cache.put("k", payload, ttl_seconds=60)
        self.assertIsNone(self.cache.get("k"))

    def test_rejects_nan(self):
        with self.assertRaises(ValueError):
            self.cache.put("k", {"rating": float("nan")}, ttl_seconds=60)


if __name__ == "__main__":
    unittest.main()
