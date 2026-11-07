from pathlib import Path
import sqlite3
import tempfile
import unittest

from shutong.engine.states import InvalidTransition, ItemStatus, ReviewReason
from shutong.store.db import Database
from shutong.store.records import ItemStore, LibraryStore, RunStore


class RecordStoreTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        db = Database(Path(self._directory.name) / "shutong.db")
        db.migrate()
        self.libraries = LibraryStore(db)
        self.runs = RunStore(db)
        self.items = ItemStore(db)
        self.lib = self.libraries.create("漫画", "manga", Path("/s"), Path("/l"))

    def test_library_round_trip_with_archive_dir(self):
        novel = self.libraries.create(
            "轻小说", "novel", Path("/b/待整理"), Path("/b/轻小说"),
            source_policy="archive", archive_dir=Path("/b/原档轻小说"),
        )
        loaded = self.libraries.get(novel.id)
        self.assertEqual(loaded.archive_dir, Path("/b/原档轻小说"))
        self.assertEqual(loaded.source_policy, "archive")

    def test_run_finish_records_counts(self):
        run_id = self.runs.create(self.lib.id, "manual")
        self.runs.finish(run_id, {"published": 3})
        item = self.items.create(self.lib.id, Path("/s/a.zip"), "v1:aa", run_id=run_id)
        self.assertEqual(item.run_id, run_id)

    def test_subject_source_is_stored_with_the_id(self):
        item = self.items.create(self.lib.id, Path("/s/a.zip"), "v1:aa")
        self.items.transition(item.id, ItemStatus.PARSED, event="parsed", parsed={})
        item = self.items.transition(item.id, ItemStatus.MATCHED, event="matched", subject_id="30002",
                                     subject_source="anilist")
        self.assertEqual((item.subject_id, item.subject_source), ("30002", "anilist"))
        self.assertEqual(item.subject_ref.key, "anilist:30002")
        other = self.items.create(self.lib.id, Path("/s/b.zip"), "v1:bb")
        self.assertIsNone(other.subject_ref)

    def test_subject_sources_by_folder(self):
        root = Path("/s")
        for name, path, source in (("a", "甲/1.cbz", "anilist"), ("b", "乙/1.cbz", "bangumi"),
                                   ("c", "散.cbz", "anilist"), ("d", "甲/2.cbz", "bangumi"),
                                   ("e", "パ/1.cbz", "anilist"), ("f", "丙/1.cbz", None)):
            item = self.items.create(self.lib.id, root / path, "v1:" + name)
            self.items.transition(item.id, ItemStatus.PARSED, event="parsed", parsed={})
            if source:
                self.items.transition(item.id, ItemStatus.MATCHED, event="matched", subject_id="1",
                                      subject_source=source)
        found = self.items.subject_sources_by_folder(self.lib.id, root)
        self.assertEqual(found, {"甲": "anilist", "乙": "bangumi", "パ": "anilist"})
        self.assertEqual(self.items.subject_sources_by_folder(self.lib.id, Path("/elsewhere")), {})

    def test_create_item_records_discovered_event(self):
        item = self.items.create(self.lib.id, Path("/s/a.zip"), "v1:aa")
        self.assertEqual(item.status, ItemStatus.DISCOVERED)
        self.assertEqual([event.kind for event in self.items.events(item.id)], ["discovered"])

    def test_transition_updates_fields_and_logs_event(self):
        item = self.items.create(self.lib.id, Path("/s/a.zip"), "v1:aa")
        item = self.items.transition(
            item.id, ItemStatus.PARSED, event="parsed",
            parsed={"title": "间谍过家家", "volume": "volume:19"},
        )
        self.assertEqual(item.parsed["title"], "间谍过家家")
        self.assertEqual(self.items.get(item.id).parsed["volume"], "volume:19")
        self.assertEqual(self.items.events(item.id)[-1].kind, "parsed")

    def test_needs_review_requires_reason(self):
        item = self.items.create(self.lib.id, Path("/s/a.zip"), "v1:aa")
        self.items.transition(item.id, ItemStatus.PARSED, event="parsed")
        with self.assertRaises(ValueError):
            self.items.transition(item.id, ItemStatus.NEEDS_REVIEW, event="review")

    def test_leaving_review_clears_reason(self):
        item = self.items.create(self.lib.id, Path("/s/a.zip"), "v1:aa")
        self.items.transition(item.id, ItemStatus.PARSED, event="parsed")
        reviewed = self.items.transition(
            item.id, ItemStatus.NEEDS_REVIEW, event="review", review_reason=ReviewReason.NAMING
        )
        self.assertEqual(reviewed.review_reason, ReviewReason.NAMING)
        self.items.transition(item.id, ItemStatus.PLANNED, event="confirmed")
        self.assertIsNone(self.items.get(item.id).review_reason)

    def test_invalid_transition_leaves_row_untouched(self):
        item = self.items.create(self.lib.id, Path("/s/a.zip"), "v1:aa")
        with self.assertRaises(InvalidTransition):
            self.items.transition(item.id, ItemStatus.PUBLISHED, event="x")
        self.assertEqual(self.items.get(item.id).status, ItemStatus.DISCOVERED)
        self.assertEqual(len(self.items.events(item.id)), 1)

    def test_unknown_field_rejected(self):
        item = self.items.create(self.lib.id, Path("/s/a.zip"), "v1:aa")
        with self.assertRaises(TypeError):
            self.items.transition(item.id, ItemStatus.PARSED, event="p", status="x")

    def test_same_fingerprint_same_library_is_unique(self):
        self.items.create(self.lib.id, Path("/s/a.zip"), "v1:aa")
        with self.assertRaises(sqlite3.IntegrityError):
            self.items.create(self.lib.id, Path("/s/b.zip"), "v1:aa")
        found = self.items.find_by_fingerprint(self.lib.id, "v1:aa")
        self.assertEqual(found.source_path, Path("/s/a.zip"))
        self.assertIsNone(self.items.find_by_fingerprint(self.lib.id, "v1:zz"))

    def test_add_event_keeps_order_and_detail(self):
        item = self.items.create(self.lib.id, Path("/s/a.zip"), "v1:aa")
        self.items.add_event(item.id, "ai_suggestion", {"confidence": 0.9, "理由": "卷号"})
        events = self.items.events(item.id)
        self.assertEqual([event.kind for event in events], ["discovered", "ai_suggestion"])
        self.assertEqual(events[-1].detail["理由"], "卷号")

    def test_library_update_fields(self):
        novel = self.libraries.create("轻小说", "novel", Path("/b/s"), Path("/b/l"), source_policy="archive",
                                      archive_dir=Path("/b/a"))
        updated = self.libraries.update(novel.id, name="小说", source_policy="keep", archive_dir=None,
                                        pdf_to_cbz=False, source_dir=Path("/c/s"), library_dir=Path("/c/l"))
        self.assertEqual((updated.name, updated.source_policy, updated.archive_dir, updated.pdf_to_cbz,
                          updated.source_dir, updated.library_dir),
                         ("小说", "keep", None, False, Path("/c/s"), Path("/c/l")))
        # Leaving archive_dir out keeps it.
        kept = self.libraries.update(self.lib.id, naming_template="{series}/{volume}{ext}")
        self.assertEqual(kept.naming_template, "{series}/{volume}{ext}")

    def test_item_overrides_round_trip(self):
        item = self.items.create(self.lib.id, Path("/s/a.zip"), "v1:aa")
        self.assertEqual(item.overrides, {})
        self.items.set_overrides(item.id, {"volume": "SP1"})
        self.assertEqual(self.items.get(item.id).overrides, {"volume": "SP1"})

    def test_item_page_filters_and_counts(self):
        for name in ("a.zip", "b.zip", "c.zip"):
            self.items.create(self.lib.id, Path("/s/迷宫饭") / name, "v1:" + name)
        page, total = self.items.page(self.lib.id, limit=2)
        self.assertEqual((len(page), total), (2, 3))
        page, total = self.items.page(self.lib.id, query="B.ZIP")
        self.assertEqual(([item.source_path.name for item in page], total), (["b.zip"], 1))
        page, total = self.items.page(self.lib.id, status=ItemStatus.PUBLISHED)
        self.assertEqual(total, 0)
        page, total = self.items.page(None, limit=10, offset=2)
        self.assertEqual((len(page), total), (1, 3))

    def test_group_key_is_stored(self):
        item = self.items.create(self.lib.id, Path("/s/迷宫饭/Vol.01.zip"), "fp-g", group_key="迷宫饭")
        self.assertEqual(item.group_key, "迷宫饭")

    def test_backfill_group_keys(self):
        with self.items.db.connect() as connection:
            for name in ("迷宫饭/Vol.01.zip", "迷宫饭/Vol.02.zip", "loose.zip"):
                connection.execute("INSERT INTO items(library_id, source_path, fingerprint, status, created_at,"
                                   " updated_at) VALUES (?, ?, ?, 'planned', 't', 't')",
                                   (self.lib.id, "/s/" + name, name))
        filled = self.items.backfill_group_keys(lambda library_id, path: path.parent.name or path.name)
        self.assertEqual(filled, 3)
        with self.items.db.connect() as connection:
            keys = [row[0] for row in connection.execute("SELECT group_key FROM items ORDER BY id")]
        self.assertEqual(keys, ["迷宫饭", "迷宫饭", "s"])
        self.assertEqual(self.items.backfill_group_keys(lambda library_id, path: "x"), 0)

    def test_include_edition_defaults_true_and_can_be_disabled(self):
        self.assertTrue(self.lib.include_edition)
        plain = self.libraries.create("无版本", "manga", Path("/s3"), Path("/l3"), include_edition=False)
        self.assertFalse(plain.include_edition)
        self.assertTrue(self.libraries.update(plain.id, include_edition=True).include_edition)

    def test_pdf_to_cbz_defaults_true_and_can_be_disabled(self):
        self.assertTrue(self.lib.pdf_to_cbz)
        kept = self.libraries.create("PDF库", "manga", Path("/s2"), Path("/l2"), pdf_to_cbz=False)
        self.assertFalse(self.libraries.get(kept.id).pdf_to_cbz)

    def test_update_fields_without_changing_status(self):
        item = self.items.create(self.lib.id, Path("/s/a.zip"), "v1:aa")
        self.items.transition(item.id, ItemStatus.PARSED, event="parsed", parsed={"v": 1})
        updated = self.items.update(item.id, event="reparsed", parsed={"v": 2})
        self.assertEqual((updated.status, updated.parsed), (ItemStatus.PARSED, {"v": 2}))
        self.assertEqual(self.items.events(item.id)[-1].kind, "reparsed")
        with self.assertRaises(TypeError):
            self.items.update(item.id, event="x", status="published")


if __name__ == "__main__":
    unittest.main()
