from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from shutong.store.ai_calls import AiCallStore
from shutong.store.db import Database
from shutong.store.records import ItemStore, LibraryStore


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 29, 10, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class AiCallStoreTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.db = Database(Path(self._directory.name) / "shutong.db")
        self.db.migrate()
        self.clock = Clock()
        self.calls = AiCallStore(self.db, clock=self.clock)
        library = LibraryStore(self.db).create("漫画", "manga", Path("/s"), Path("/l"))
        self.item = ItemStore(self.db).create(library.id, Path("/s/a.zip"), "v1:a").id

    def _record(self, **overrides):
        values = dict(item_id=self.item, purpose="choose_subject", model="m", request_json="{}",
                      response_text='{"subject_id": 1}', error=None, duration_ms=12)
        values.update(overrides)
        return self.calls.record(**values)

    def test_record_and_count_since(self):
        self._record()
        self.clock.now += timedelta(hours=1)
        self._record(error="boom", response_text=None)
        self.assertEqual(self.calls.count_since(datetime(2026, 10, 29, tzinfo=timezone.utc)), 2)
        self.assertEqual(self.calls.count_since(datetime(2026, 10, 29, 10, 30, tzinfo=timezone.utc)), 1)
        calls = self.calls.for_item(self.item)
        self.assertEqual([(call.error, call.duration_ms) for call in calls], [(None, 12), ("boom", 12)])

    def test_mark_adopted(self):
        call_id = self._record()
        self.calls.mark_adopted(call_id)
        self.assertTrue(self.calls.for_item(self.item)[0].adopted)

    def test_item_delete_keeps_call_with_null_item(self):
        call_id = self._record()
        with self.db.connect() as connection:
            connection.execute("DELETE FROM items WHERE id = ?", (self.item,))
        with self.db.connect() as connection:
            row = connection.execute("SELECT item_id FROM ai_calls WHERE id = ?", (call_id,)).fetchone()
        self.assertIsNone(row["item_id"])


if __name__ == "__main__":
    unittest.main()
