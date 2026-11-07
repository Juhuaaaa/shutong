from pathlib import Path
import unittest

from shutong.engine.ai_recognize import BATCH_SIZE
from shutong.engine.states import ItemStatus, ReviewReason
from shutong.store.records import LibraryStore

from .novel.test_epub import build_epub
from .reader_ai import ReaderAi
from .test_match import FakeSource, subject
from .test_organizer_scan import OrganizerFixture


class OrganizerReviewTests(OrganizerFixture):
    def reviewed(self, relative, **unsure):
        self.zip(relative)
        folder = relative.split("/")[0]
        organizer = self.organizer(ai=ReaderAi(**(unsure or {"unsure_series": {folder}})))
        organizer.scan(self.library.id)
        item = next(item for item in self.all_items() if item.source_path.as_posix().endswith(relative))
        self.assertEqual(item.status, ItemStatus.NEEDS_REVIEW)
        return organizer, item

    def test_confirm_keeps_the_choice_on_the_item_and_replans(self):
        organizer, item = self.reviewed("[]/Vol.01.zip")
        result = organizer.confirm([item.id], title="迷宫饭", edition=None, bgm=133315)
        item = self.items.get(item.id)
        self.assertEqual(item.status, ItemStatus.PLANNED)
        self.assertEqual(item.target_path.as_posix(), "迷宫饭/迷宫饭 Vol.01.cbz")
        self.assertEqual(item.overrides, {"title": "迷宫饭", "bgm": 133315})
        self.assertEqual(result, {"replanned": 1, "skipped": 0})

    def test_confirmed_item_keeps_its_choice_when_read_again(self):
        organizer, item = self.reviewed("[]/Vol.01.zip")
        organizer.confirm([item.id], title="迷宫饭", edition=None, bgm=133315)
        with self.db.connect() as connection:
            connection.execute("UPDATE items SET status = 'needs_review', review_reason = 'metadata' WHERE id = ?",
                               (item.id,))
        organizer.reidentify([item.id])
        self.assertEqual(self.items.get(item.id).target_path.as_posix(), "迷宫饭/迷宫饭 Vol.01.cbz")

    def test_skip_metadata_organizes_without_asking_bangumi(self):
        organizer, item = self.reviewed("[]/Vol.01.zip")
        self.source.searches.clear()
        organizer.confirm([item.id], title="天鹅绒之吻", skip_metadata=True)
        item = self.items.get(item.id)
        self.assertEqual((item.status, item.subject_id), (ItemStatus.PLANNED, None))
        self.assertEqual(item.target_path.as_posix(), "天鹅绒之吻/天鹅绒之吻 Vol.01.cbz")
        self.assertEqual(item.overrides, {"title": "天鹅绒之吻", "no_metadata": True})
        self.assertEqual(self.source.searches, [])
        self.assertIn("no_metadata", [event.kind for event in self.items.events(item.id)])

    def test_picking_a_subject_later_drops_the_skip(self):
        organizer, item = self.reviewed("[]/Vol.01.zip")
        organizer.confirm([item.id], title="迷宫饭", skip_metadata=True)
        with self.db.connect() as connection:
            connection.execute("UPDATE items SET status = 'needs_review', review_reason = 'metadata' WHERE id = ?",
                               (item.id,))
        organizer.confirm([item.id], bgm=133315)
        item = self.items.get(item.id)
        self.assertEqual((item.status, item.subject_id), (ItemStatus.PLANNED, "133315"))
        self.assertNotIn("no_metadata", item.overrides)

    def test_confirm_volume_override(self):
        organizer, item = self.reviewed("迷宫饭/迷宫饭 番外.zip", unsure={"迷宫饭 番外.zip"})
        self.assertEqual(item.review_reason, ReviewReason.VOLUME)
        organizer.confirm([item.id], title=None, edition=None, bgm=None, volumes={item.id: "SP1"})
        item = self.items.get(item.id)
        self.assertEqual(item.status, ItemStatus.PLANNED)
        self.assertIn("SP", item.target_path.name)
        self.assertEqual(item.overrides, {"volume": "SP1"})

    def published(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        organizer = self.organizer()
        organizer.scan(self.library.id)
        [item] = self.all_items()
        organizer.execute([item.id])
        target = self.library_dir / self.items.get(item.id).target_path
        self.assertTrue(target.exists())
        return organizer, item, target

    def test_reorganize_deletes_old_target_then_replans(self):
        organizer, item, target = self.published()
        result = organizer.reorganize([item.id], title="迷宫饭 新", bgm=133315)
        item = self.items.get(item.id)
        self.assertFalse(target.exists())
        self.assertFalse((self.library_dir / ".shutong" / "trash").exists())
        self.assertEqual((item.status, item.target_path.as_posix()),
                         (ItemStatus.PLANNED, "迷宫饭 新/迷宫饭 新 Vol.01.cbz"))
        self.assertEqual((result["deleted"], result["replanned"]), (1, 1))
        self.assertIn("target_deleted", [event.kind for event in self.items.events(item.id)])

    def test_reorganize_to_same_target_succeeds(self):
        organizer, item, target = self.published()
        organizer.reorganize([item.id])
        item = self.items.get(item.id)
        self.assertEqual((item.status, self.library_dir / item.target_path), (ItemStatus.PLANNED, target))
        organizer.execute([item.id])
        self.assertTrue(target.exists())

    def test_reorganize_skips_items_that_are_not_published(self):
        organizer, item = self.reviewed("[]/Vol.01.zip")
        self.assertEqual(organizer.reorganize([item.id], title="x")["skipped"], 1)
        self.assertEqual(self.items.get(item.id).status, ItemStatus.NEEDS_REVIEW)

    def test_cancel(self):
        organizer, item, target = self.published()
        organizer.reorganize([item.id], title="迷宫饭 新", bgm=133315)
        self.assertEqual(organizer.cancel([item.id])["cancelled"], 1)
        self.assertEqual(self.items.get(item.id).status, ItemStatus.CANCELLED)

    def test_reorganize_refuses_when_the_source_is_gone(self):
        archive = self.root / "archive"
        self.library = LibraryStore(self.db).create("漫画-archive", "manga", self.source_dir, self.library_dir,
                                                    source_policy="archive", archive_dir=archive)
        organizer, item, target = self.published()
        self.assertFalse(self.items.get(item.id).source_path.exists())  # moved to the archive dir
        result = organizer.reorganize([item.id], title="迷宫饭 新", bgm=133315)
        self.assertEqual((result["deleted"], result["skipped"]), (0, 1))
        self.assertTrue(target.exists())
        self.assertEqual(self.items.get(item.id).status, ItemStatus.PUBLISHED)

    def test_reorganize_with_a_bad_choice_changes_nothing(self):
        organizer, item, target = self.published()
        for choice in ({"title": "Fate/Zero"}, {"volumes": {item.id: "abc"}}, {"edition": " x"}):
            with self.subTest(choice=choice):
                with self.assertRaises(ValueError):
                    organizer.reorganize([item.id], **choice)
                self.assertTrue(target.exists())
                self.assertEqual(self.items.get(item.id).status, ItemStatus.PUBLISHED)

    def test_bad_title_message_is_chinese(self):
        organizer, item = self.reviewed("[]/Vol.01.zip")
        with self.assertRaisesRegex(ValueError, "系列名"):
            organizer.confirm([item.id], title="Fate/Zero")
        self.assertEqual(self.items.get(item.id).overrides, {})

    def test_confirm_with_only_a_subject_names_the_series(self):
        organizer, item = self.reviewed("[]/Vol.01.zip")
        self.assertEqual(item.review_reason, ReviewReason.NAMING)
        organizer.confirm([item.id], bgm=133315)
        item = self.items.get(item.id)
        self.assertEqual((item.status, item.target_path.as_posix()), (ItemStatus.PLANNED, "迷宫饭/迷宫饭 Vol.01.cbz"))


if __name__ == "__main__":
    unittest.main()


class NovelReviewTests(OrganizerFixture):
    def setUp(self):
        super().setUp()
        self.library = LibraryStore(self.db).create("轻小说", "novel", self.source_dir, self.library_dir)
        novel = subject(439286, "某暗部的少女共栖", name="とある暗部の少女共棲", platform="小说", total=3)
        self.source = FakeSource([novel], subjects={439286: novel})

    def epub(self, relative):
        path = self.source_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        build_epub(path, title=path.stem)
        return path

    def test_a_volume_typed_in_review_is_organized(self):
        self.epub("魔法禁书目录/某暗部 2X.epub")
        organizer = self.organizer(ai=ReaderAi(unsure={"某暗部 2X.epub"}))
        organizer.scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual(item.status, ItemStatus.NEEDS_REVIEW)
        organizer.confirm([item.id], title="某暗部的少女共栖", bgm=439286, volumes={item.id: "2"})
        item = self.items.get(item.id)
        self.assertEqual((item.status, item.error), (ItemStatus.PLANNED, None))
        self.assertEqual(item.target_path, Path("某暗部的少女共栖/某暗部的少女共栖 Vol.02.epub"))

    def test_a_range_is_refused_before_anything_changes(self):
        self.epub("魔法禁书目录/某暗部 2X.epub")
        organizer = self.organizer(ai=ReaderAi(unsure={"某暗部 2X.epub"}))
        organizer.scan(self.library.id)
        [item] = self.all_items()
        with self.assertRaisesRegex(ValueError, "轻小说"):
            organizer.confirm([item.id], volumes={item.id: "1-5"})
        self.assertEqual((self.items.get(item.id).status, self.items.get(item.id).overrides),
                         (ItemStatus.NEEDS_REVIEW, {}))

    def test_novels_never_carry_an_edition(self):
        self.epub("魔法禁书目录/某暗部 Vol.01.epub")
        organizer = self.organizer(ai=ReaderAi(series={"魔法禁书目录": {"title": "某暗部的少女共栖", "edition": "台版"}}))
        organizer.scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual(item.target_path, Path("某暗部的少女共栖/某暗部的少女共栖 Vol.01.epub"))
        self.assertIsNone(item.parsed["edition"])

    def test_later_batches_are_told_every_work_of_the_folder(self):
        names = ["第{0:03d}.epub".format(n) for n in range(1, BATCH_SIZE + 2)]
        for name in names:
            self.epub("魔法禁书目录/" + name)

        class TwoWorks(ReaderAi):
            def complete_json(self, purpose, system, payload, *, item_id=None):
                answer, call = super().complete_json(purpose, system, payload, item_id=item_id)
                if purpose == "recognize":
                    answer["series"].append({"id": "s9", "title": "某暗部的少女共栖", "edition": None, "search_titles": [],
                                             "confidence": 0.97, "reason": "测试"})
                    answer["files"][0].update(series="s9", unit="volume", number="1", confidence=0.97)
                return answer, call

        ai = TwoWorks(series={"魔法禁书目录": {"title": "魔法禁书目录"}})
        self.organizer(ai=ai).scan(self.library.id)
        recognize = [request["payload"] for request in ai.requests if request["purpose"] == "recognize"]
        self.assertEqual({entry["title"] for entry in recognize[1]["settled_series"]}, {"魔法禁书目录", "某暗部的少女共栖"})
