from dataclasses import replace
import io
import os
from pathlib import Path
import unittest
from unittest import mock
import zipfile

from PIL import Image

from shutong.engine.kinds.manga.comicinfo import read_comic_info
from shutong.engine.metadata_edit import ManualMetadata
from shutong.engine.organizer import Organizer
from shutong.engine.states import ItemStatus, ReviewReason
from shutong.metadata.base import MetadataUnavailable
from shutong.store.journal import JournalStore
from shutong.store.records import LibraryStore

from .reader_ai import ReaderAi
from .test_organizer_scan import DUNGEON, JPEG, OrganizerFixture


def jpeg(colour):
    buffer = io.BytesIO()
    Image.new("RGB", (272, 400), colour).save(buffer, format="JPEG")
    return buffer.getvalue()


class OverwriteTests(OrganizerFixture):
    def use(self, **options):
        self.library = LibraryStore(self.db).update(self.library.id, **options)

    def publish_first(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        organizer = self.organizer()
        organizer.scan(self.library.id, on_planned=organizer.execute)
        [first] = self.all_items()
        self.assertEqual(first.status, ItemStatus.PUBLISHED)
        return organizer, first

    def test_always_replaces_the_file_and_retires_the_old_item(self):
        organizer, first = self.publish_first()
        final = self.library_dir / first.target_path
        before = final.read_bytes()
        self.use(overwrite_policy="always")
        self.zip("迷宫饭-新/迷宫饭 Vol.01.zip")
        organizer = self.organizer(ai=ReaderAi(series={"迷宫饭-新": {"title": "迷宫饭"}}))
        organizer.scan(self.library.id, on_planned=organizer.execute)
        [old, new] = self.all_items()
        self.assertEqual((old.status, new.status), (ItemStatus.DUPLICATE, ItemStatus.PUBLISHED))
        self.assertEqual(new.target_path, first.target_path)
        self.assertNotIn("replaces", new.plan)
        self.assertNotEqual(final.read_bytes(), before)
        self.assertEqual(self.items.published_owner(self.library.id, first.target_path), new.id)
        self.assertEqual(self.items.events(old.id)[-1].kind, "replaced")
        self.assertIn("target_replaced", [event.kind for event in self.items.events(new.id)])
        self.assertEqual(list((self.library_dir / "迷宫饭").iterdir()), [final])

    def test_a_replaced_file_of_another_name_goes_away(self):
        self.use(overwrite_policy="always")
        old = self.library_dir / "迷宫饭" / "旧名字 Vol.01.cbz"
        old.parent.mkdir()
        old.write_bytes(b"old")
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        organizer = self.organizer()
        organizer.scan(self.library.id, on_planned=organizer.execute)
        self.assertEqual([path.name for path in old.parent.iterdir()], ["迷宫饭 Vol.01.cbz"])

    def test_never_leaves_the_library_alone(self):
        organizer, first = self.publish_first()
        final = self.library_dir / first.target_path
        before = final.read_bytes()
        self.zip("迷宫饭-新/迷宫饭 Vol.01.zip")
        organizer = self.organizer(ai=ReaderAi(series={"迷宫饭-新": {"title": "迷宫饭"}}))
        organizer.scan(self.library.id, on_planned=organizer.execute)
        [old, new] = self.all_items()
        self.assertEqual((old.status, new.status), (ItemStatus.PUBLISHED, ItemStatus.DUPLICATE))
        self.assertEqual(final.read_bytes(), before)

    def test_a_file_replaced_by_size_is_scanned_only_once(self):
        organizer, first = self.publish_first()
        self.use(overwrite_policy="larger")
        path = self.source_dir / "迷宫饭-新" / "迷宫饭 Vol.01.zip"
        path.parent.mkdir()
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("01.jpg", JPEG + b"x" * 500000)
        organizer = self.organizer(ai=ReaderAi(series={"迷宫饭-新": {"title": "迷宫饭"}}))
        organizer.scan(self.library.id, on_planned=organizer.execute)
        self.assertEqual([item.status for item in self.all_items()], [ItemStatus.DUPLICATE, ItemStatus.PUBLISHED])
        organizer.scan(self.library.id, on_planned=organizer.execute)
        self.assertEqual([item.status for item in self.all_items()], [ItemStatus.DUPLICATE, ItemStatus.PUBLISHED])

    def test_the_newest_source_is_remembered_in_the_plan(self):
        _, first = self.publish_first()
        self.assertEqual(first.plan["source_mtime"], first.source_path.stat().st_mtime)

    def test_original_names_end_to_end(self):
        self.use(rename_files=False)
        self.zip("迷宫饭/[组]迷宫饭 Vol.01.zip")
        organizer = self.organizer()
        organizer.scan(self.library.id, on_planned=organizer.execute)
        [item] = self.all_items()
        self.assertEqual((item.status, item.target_path), (ItemStatus.PUBLISHED, Path("迷宫饭/[组]迷宫饭 Vol.01.cbz")))
        self.zip("迷宫饭-二/别的名字 Vol.01.zip")
        organizer = self.organizer(ai=ReaderAi(series={"迷宫饭-二": {"title": "迷宫饭"}}))
        organizer.scan(self.library.id, on_planned=organizer.execute)
        self.assertEqual(self.all_items()[1].status, ItemStatus.DUPLICATE)


class RefreshMetadataTests(OrganizerFixture):
    def published(self, *names):
        for name in names:
            self.zip(name)
        organizer = self.organizer()
        organizer.scan(self.library.id, on_planned=organizer.execute)
        return organizer, self.all_items()

    def changed_subject(self):
        return replace(DUNGEON, summary="新的简介", writers=("九井谅子",), publisher="新出版社")

    def test_writes_what_bangumi_says_now_into_the_file(self):
        organizer, [item] = self.published("迷宫饭/迷宫饭 Vol.01.zip")
        self.source.subjects[133315] = self.changed_subject()
        result = organizer.refresh_metadata([item.id])
        self.assertEqual((result["refreshed"], result["unchanged"], result["skipped"], result["failed"]), (1, 0, 0, 0))
        self.assertEqual(self.source.gets[-1], ("133315", True))
        fields = read_comic_info(self.library_dir / item.target_path)
        self.assertEqual((fields["Summary"], fields["Publisher"]), ("新的简介", "新出版社"))
        self.assertEqual(self.items.get(item.id).plan["metadata"]["publisher"], "新出版社")
        self.assertIn("metadata_refreshed", [event.kind for event in self.items.events(item.id)])
        self.assertEqual(result["series"], [(self.library.id, "迷宫饭")])

    def test_a_file_bangumi_has_nothing_new_for_is_not_touched(self):
        organizer, [item] = self.published("迷宫饭/迷宫饭 Vol.01.zip")
        final = self.library_dir / item.target_path
        os.utime(final, (1000, 1000))
        result = organizer.refresh_metadata([item.id])
        self.assertEqual((result["refreshed"], result["unchanged"]), (0, 1))
        self.assertEqual(final.stat().st_mtime, 1000)

    def test_asks_bangumi_once_per_subject(self):
        organizer, items = self.published("迷宫饭/迷宫饭 Vol.01.zip", "迷宫饭/迷宫饭 Vol.02.zip")
        self.source.gets.clear()
        organizer.refresh_metadata([item.id for item in items])
        self.assertEqual(self.source.gets, [("133315", True)])

    def test_what_a_person_filled_in_stays(self):
        organizer, [item] = self.published("迷宫饭/迷宫饭 Vol.01.zip")
        organizer.edit_metadata([item.id], manual=ManualMetadata(publisher="手填的"))
        self.source.subjects[133315] = self.changed_subject()
        result = organizer.refresh_metadata([item.id])
        self.assertEqual((result["refreshed"], result["skipped"]), (0, 1))
        self.assertEqual(read_comic_info(self.library_dir / item.target_path)["Publisher"], "手填的")

    def test_items_without_a_subject_or_not_published_are_skipped(self):
        organizer, [item] = self.published("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("[]/Vol.01.zip")
        organizer = self.organizer(ai=ReaderAi(unsure_series={"[]"}))
        organizer.scan(self.library.id)
        waiting = self.all_items()[1]
        self.assertEqual(waiting.status, ItemStatus.NEEDS_REVIEW)
        self.assertEqual(organizer.refresh_metadata([waiting.id])["skipped"], 1)

    def test_bangumi_being_away_stops_nothing_and_changes_nothing(self):
        organizer, [item] = self.published("迷宫饭/迷宫饭 Vol.01.zip")
        self.source.error = MetadataUnavailable("连不上")
        result = organizer.refresh_metadata([item.id])
        self.assertEqual((result["refreshed"], result["failed"]), (0, 1))
        self.assertEqual(self.items.get(item.id).status, ItemStatus.PUBLISHED)

    def test_a_missing_file_is_a_failure_of_that_file(self):
        organizer, items = self.published("迷宫饭/迷宫饭 Vol.01.zip", "迷宫饭/迷宫饭 Vol.02.zip")
        (self.library_dir / items[0].target_path).unlink()
        self.source.subjects[133315] = self.changed_subject()
        result = organizer.refresh_metadata([item.id for item in items])
        self.assertEqual((result["refreshed"], result["failed"]), (1, 1))


class CoverTests(OrganizerFixture):
    def published(self):
        source = self.source_dir / "迷宫饭" / "迷宫饭 Vol.01.zip"
        source.parent.mkdir()
        with zipfile.ZipFile(source, "w") as archive:
            for number, colour in ((1, (10, 10, 10)), (2, (200, 200, 200))):
                archive.writestr("{0:02d}.jpg".format(number), jpeg(colour))
        organizer = self.organizer()
        organizer.scan(self.library.id, on_planned=organizer.execute)
        [item] = self.all_items()
        self.assertEqual(item.status, ItemStatus.PUBLISHED)
        return organizer, item

    def test_a_chosen_cover_survives_reorganizing(self):
        organizer, item = self.published()
        organizer.set_cover(item.id, "002.jpg")
        organizer.reorganize([item.id])
        organizer.execute([item.id])
        item = self.items.get(item.id)
        self.assertEqual(item.status, ItemStatus.PUBLISHED)
        with zipfile.ZipFile(self.library_dir / item.target_path) as archive:
            self.assertEqual(archive.read("000.jpg"), archive.read("002.jpg"))

    def test_a_cover_survives_editing_the_metadata(self):
        organizer, item = self.published()
        organizer.set_cover(item.id, "002.jpg")
        organizer.edit_metadata([item.id], manual=ManualMetadata(publisher="手填的"))
        with zipfile.ZipFile(self.library_dir / item.target_path) as archive:
            self.assertIn("000.jpg", archive.namelist())

    def test_a_cover_that_cannot_be_restored_does_not_undo_the_organizing(self):
        organizer, item = self.published()
        organizer.set_cover(item.id, "002.jpg")
        self.items.set_overrides(item.id, {"cover": {"page": "999.jpg"}})
        organizer.reorganize([item.id])
        organizer.execute([item.id])
        item = self.items.get(item.id)
        self.assertEqual(item.status, ItemStatus.PUBLISHED)
        self.assertIn("cover_failed", [event.kind for event in self.items.events(item.id)])

    def test_a_record_without_a_plan_can_still_get_a_cover(self):
        # Records imported from the old tool have no plan: nothing names their series for the media server.
        organizer, item = self.published()
        self.items.update(item.id, event="legacy_fixed", plan={})
        self.assertEqual(organizer.set_cover(item.id, "002.jpg")["series"], [])
        with zipfile.ZipFile(self.library_dir / item.target_path) as archive:
            self.assertIn("000.jpg", archive.namelist())

    def test_novels_keep_the_cover_they_came_with(self):
        organizer, item = self.published()
        library = LibraryStore(self.db).create("轻小说", "novel", self.source_dir, self.library_dir)
        with self.db.connect() as connection:
            connection.execute("UPDATE items SET library_id = ? WHERE id = ?", (library.id, item.id))
        with self.assertRaisesRegex(ValueError, "只有漫画"):
            organizer.set_cover(item.id, "002.jpg")
        self.assertEqual(organizer.crop_jackets([item.id])["skipped"], 1)

    def test_only_organized_files_get_a_cover(self):
        organizer, item = self.published()
        organizer.reorganize([item.id])
        with self.assertRaisesRegex(ValueError, "已整理"):
            organizer.set_cover(item.id, "002.jpg")


class Killed(BaseException):
    """Stands in for the process dying."""


class OrganizerExecuteTests(OrganizerFixture):
    def planned(self, *relatives, policy="keep", archive_dir=None):
        if policy != "keep":
            self.library = LibraryStore(self.db).create(
                "漫画-" + policy, "manga", self.source_dir, self.library_dir, source_policy=policy,
                archive_dir=archive_dir)
        sources = [self.zip(relative) for relative in relatives]
        organizer = self.organizer()
        organizer.scan(self.library.id)
        items = [item for item in self.all_items() if item.library_id == self.library.id]
        self.assertEqual({item.status for item in items}, {ItemStatus.PLANNED})
        return organizer, items, sources

    def test_execute_publishes_and_keeps_source(self):
        organizer, [item], [source] = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        result = organizer.execute([item.id])
        published = self.items.get(item.id)
        self.assertEqual((published.status, result["published"]), (ItemStatus.PUBLISHED, 1))
        final = self.library_dir / "迷宫饭" / "迷宫饭 Vol.01.cbz"
        fields = read_comic_info(final)
        self.assertEqual((fields["Series"], fields["Volume"], fields["Web"]),
                         ("迷宫饭", "1", "https://bgm.tv/subject/133315"))
        self.assertTrue(source.exists())
        kinds = [event.kind for event in self.items.events(item.id)]
        self.assertEqual(kinds[-4:], ["confirmed", "building", "published", "source_disposed"])
        self.assertEqual(list((self.library_dir / ".shutong" / "staging").iterdir()), [])

    def test_execute_archive_policy_moves_source(self):
        archive = self.root / "原档"
        organizer, [item], [source] = self.planned("迷宫饭/迷宫饭 Vol.01.zip", policy="archive", archive_dir=archive)
        organizer.execute([item.id])
        self.assertFalse(source.exists())
        self.assertTrue((archive / "迷宫饭" / "迷宫饭 Vol.01.zip").exists())

    def test_execute_delete_policy_deletes_source(self):
        organizer, [item], [source] = self.planned("迷宫饭/迷宫饭 Vol.01.zip", policy="delete")
        organizer.execute([item.id])
        self.assertFalse(source.exists())
        self.assertFalse((self.source_dir / ".shutong").exists())

    def test_changed_source_is_cancelled_and_the_next_scan_redoes_it(self):
        organizer, [item], [source] = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("01.jpg", JPEG + b"changed")
        organizer.execute([item.id])
        changed = self.items.get(item.id)
        self.assertEqual(changed.status, ItemStatus.CANCELLED)
        self.assertIn("source_changed", [event.kind for event in self.items.events(item.id)])
        self.assertFalse((self.library_dir / "迷宫饭").exists())
        organizer.scan(self.library.id)
        fresh = [other for other in self.all_items() if other.id != item.id]
        self.assertEqual([other.status for other in fresh], [ItemStatus.PLANNED])

    def test_missing_source_is_cancelled_and_comes_back_when_it_returns(self):
        organizer, [item], [source] = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        moved = self.root / "elsewhere.zip"
        source.rename(moved)
        organizer.execute([item.id])
        self.assertEqual(self.items.get(item.id).status, ItemStatus.CANCELLED)
        self.assertIn("source_missing", [event.kind for event in self.items.events(item.id)])
        moved.rename(source)
        organizer.scan(self.library.id)
        self.assertEqual(self.items.get(item.id).status, ItemStatus.PLANNED)

    def test_user_cancelled_item_stays_cancelled_on_rescan(self):
        organizer, [item], _ = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        organizer.cancel([item.id])
        organizer.scan(self.library.id)
        self.assertEqual(self.items.get(item.id).status, ItemStatus.CANCELLED)

    def test_source_spelled_in_another_unicode_form_is_found(self):
        import unicodedata

        organizer, [item], [source] = self.planned("街角魔族/伊藤いづも Vol.01.zip")
        decomposed = Path(unicodedata.normalize("NFD", str(source)))
        with self.db.connect() as connection:
            connection.execute("UPDATE items SET source_path = ? WHERE id = ?", (str(decomposed), item.id))
        self.assertEqual(organizer.execute([item.id])["published"], 1)

    def test_build_failure_marks_failed_and_cleans_staging(self):
        organizer, [item], [source] = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        with mock.patch("shutong.engine.kinds.manga.adapter.collect_archive_pages",
                        side_effect=ValueError("corrupt archive")):
            result = organizer.execute([item.id])
        failed = self.items.get(item.id)
        self.assertEqual((failed.status, result["failed"]), (ItemStatus.FAILED, 1))
        self.assertIn("corrupt archive", failed.error)
        self.assertTrue(source.exists())
        self.assertEqual(list((self.library_dir / ".shutong" / "staging").iterdir()), [])
        self.assertEqual(JournalStore(self.db).pending(), [])

    def test_failure_is_explained_in_chinese_and_keeps_the_raw_error(self):
        cases = [
            (zipfile.BadZipFile("File is not a zip file"), "压缩包损坏，或者不是有效的压缩包"),
            (OSError(28, "No space left on device"), "磁盘空间不足"),
            (PermissionError(13, "Permission denied"), "没有权限读写文件"),
            (ValueError("archive contains too many files"), "压缩包里的文件太多（超过 30000 个）"),
            (ValueError("PDF is encrypted"), "PDF 有密码保护，读不出来"),
        ]
        organizer, items, _ = self.planned(*["迷宫饭/迷宫饭 Vol.0{0}.zip".format(n) for n in range(1, 6)])
        for item, (error, expected) in zip(items, cases):
            with self.subTest(expected=expected):
                with mock.patch("shutong.engine.kinds.manga.adapter.collect_archive_pages", side_effect=error):
                    organizer.execute([item.id])
                failed = self.items.get(item.id)
                self.assertEqual((failed.status, failed.error), (ItemStatus.FAILED, expected))
                [event] = [e for e in self.items.events(item.id) if e.kind == "failed"]
                self.assertEqual(event.detail["error"], expected)
                self.assertIn(type(error).__name__, event.detail["raw"])

    def test_retried_item_that_publishes_drops_the_old_error(self):
        organizer, [item], _ = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        with mock.patch("shutong.engine.kinds.manga.adapter.collect_archive_pages",
                        side_effect=ValueError("archive contains too many files")):
            organizer.execute([item.id])
        organizer.retry([item.id])
        organizer.execute([item.id])
        published = self.items.get(item.id)
        self.assertEqual((published.status, published.error), (ItemStatus.PUBLISHED, None))

    def test_unknown_failure_still_says_what_happened(self):
        organizer, [item], _ = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        with mock.patch("shutong.engine.kinds.manga.adapter.collect_archive_pages",
                        side_effect=ValueError("corrupt archive")):
            organizer.execute([item.id])
        self.assertEqual(self.items.get(item.id).error, "整理时出错：corrupt archive")

    def test_target_taken_is_found_before_building(self):
        organizer, [item], _ = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        target = self.library_dir / "迷宫饭" / "迷宫饭 Vol.01.cbz"
        target.parent.mkdir()
        target.write_bytes(b"someone else")
        with mock.patch("shutong.engine.kinds.manga.adapter.MangaAdapter.build") as build:
            organizer.execute([item.id])
        build.assert_not_called()
        conflict = self.items.get(item.id)
        self.assertEqual((conflict.status, conflict.review_reason), (ItemStatus.NEEDS_REVIEW, ReviewReason.CONFLICT))
        self.assertEqual(self.items.events(item.id)[-1].detail["note"], "目标位置已经有文件了")

    def test_too_little_disk_space_fails_before_building(self):
        organizer, [item], _ = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        with mock.patch("shutong.engine.failure.shutil.disk_usage", return_value=(10**9, 10**9, 1024)), \
                mock.patch("shutong.engine.kinds.manga.adapter.MangaAdapter.build") as build:
            organizer.execute([item.id])
        build.assert_not_called()
        failed = self.items.get(item.id)
        self.assertEqual(failed.status, ItemStatus.FAILED)
        self.assertTrue(failed.error.startswith("库所在的磁盘空间不足"), failed.error)

    def test_target_taken_at_publish_is_conflict(self):
        organizer, [item], _ = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        target = self.library_dir / "迷宫饭" / "迷宫饭 Vol.01.cbz"
        target.parent.mkdir()
        target.write_bytes(b"someone else")
        organizer.execute([item.id])
        conflict = self.items.get(item.id)
        self.assertEqual((conflict.status, conflict.review_reason), (ItemStatus.NEEDS_REVIEW, ReviewReason.CONFLICT))
        self.assertEqual(target.read_bytes(), b"someone else")

    def test_execute_skips_non_planned(self):
        organizer, [item], _ = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        organizer.execute([item.id])
        result = organizer.execute([item.id])
        self.assertEqual((result["skipped"], self.items.get(item.id).status), (1, ItemStatus.PUBLISHED))

    def test_recover_after_crash_before_move(self):
        organizer, [item], _ = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        with mock.patch("shutong.engine.publish.no_overwrite_move", side_effect=Killed):
            with self.assertRaises(Killed):
                organizer.execute([item.id])
        self.assertEqual(self.items.get(item.id).status, ItemStatus.BUILDING)
        restarted = self.organizer()
        restarted.recover()
        self.assertEqual(self.items.get(item.id).status, ItemStatus.READY)
        self.assertEqual(list((self.library_dir / ".shutong" / "staging").iterdir()), [])
        restarted.execute([item.id])
        self.assertEqual(self.items.get(item.id).status, ItemStatus.PUBLISHED)

    def test_recover_after_crash_after_move_finishes_disposal(self):
        organizer, [item], [source] = self.planned("迷宫饭/迷宫饭 Vol.01.zip", policy="delete")
        with mock.patch.object(JournalStore, "mark_published", side_effect=Killed):
            with self.assertRaises(Killed):
                organizer.execute([item.id])
        self.organizer().recover()
        recovered = self.items.get(item.id)
        self.assertEqual(recovered.status, ItemStatus.PUBLISHED)
        self.assertTrue((self.library_dir / "迷宫饭" / "迷宫饭 Vol.01.cbz").exists())
        self.assertFalse(source.exists())

    def test_recover_building_item_without_journal_row(self):
        organizer, [item], _ = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        self.items.transition(item.id, ItemStatus.READY, event="confirmed")
        self.items.transition(item.id, ItemStatus.BUILDING, event="building")
        self.organizer().recover()
        self.assertEqual(self.items.get(item.id).status, ItemStatus.READY)

    def test_recover_leaves_an_unmounted_library_alone(self):
        organizer, [item], _ = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        with mock.patch.object(JournalStore, "mark_published", side_effect=Killed):
            with self.assertRaises(Killed):
                organizer.execute([item.id])
        hidden = self.library_dir.with_name("library-unmounted")
        self.library_dir.rename(hidden)  # the NAS pool is not mounted yet when the container starts
        self.organizer().recover()
        self.assertEqual(self.items.get(item.id).status, ItemStatus.BUILDING)
        self.assertIsNotNone(JournalStore(self.db).get(item.id))
        hidden.rename(self.library_dir)
        self.organizer().recover()
        self.assertEqual(self.items.get(item.id).status, ItemStatus.PUBLISHED)

    def test_items_listing(self):
        organizer, items, _ = self.planned("迷宫饭/迷宫饭 Vol.01.zip", "迷宫饭/迷宫饭 Vol.02.zip")
        organizer.execute([items[0].id])
        self.assertEqual([item.id for item in self.items.list(self.library.id, ItemStatus.PLANNED)], [items[1].id])
        self.assertEqual(len(self.items.list(self.library.id)), 2)

    def test_interrupted_scan_resumes_on_rescan(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        organizer = self.organizer()
        with mock.patch.object(Organizer, "_plan", side_effect=Killed):
            with self.assertRaises(Killed):
                organizer.scan(self.library.id)
        self.assertEqual({item.status for item in self.all_items()}, {ItemStatus.MATCHED})
        self.organizer().scan(self.library.id)
        self.assertEqual({item.status for item in self.all_items()}, {ItemStatus.PLANNED})

    def test_crash_after_journal_published_recovers_as_published(self):
        organizer, [item], [source] = self.planned("迷宫饭/迷宫饭 Vol.01.zip", policy="delete")
        from shutong.store.records import ItemStore
        real = ItemStore.transition

        def die_on_published(store, item_id, target, **kwargs):
            if target is ItemStatus.PUBLISHED:
                raise Killed
            return real(store, item_id, target, **kwargs)

        with mock.patch.object(ItemStore, "transition", die_on_published):
            with self.assertRaises(Killed):
                organizer.execute([item.id])
        self.organizer().recover()
        self.assertEqual(self.items.get(item.id).status, ItemStatus.PUBLISHED)
        self.assertFalse(source.exists())

    def test_retry_reprocesses_parked_failed_and_duplicate_items(self):
        from shutong.metadata.base import MetadataUnavailable
        from .test_match import FakeSource

        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        offline = FakeSource(error=MetadataUnavailable("down"))
        self.organizer(source=offline).scan(self.library.id)
        [item] = self.all_items()
        self.organizer().retry([item.id])
        self.assertEqual(self.items.get(item.id).status, ItemStatus.PLANNED)

        organizer = self.organizer()
        with mock.patch("shutong.engine.kinds.manga.adapter.collect_archive_pages", side_effect=ValueError("bad")):
            organizer.execute([item.id])
        self.assertEqual(self.items.get(item.id).status, ItemStatus.FAILED)
        organizer.retry([item.id])
        self.assertEqual(self.items.get(item.id).status, ItemStatus.READY)
        organizer.execute([item.id])
        self.assertEqual(self.items.get(item.id).status, ItemStatus.PUBLISHED)

    def test_retry_of_duplicate_replans(self):
        (self.library_dir / "迷宫饭").mkdir()
        existing = self.library_dir / "迷宫饭" / "迷宫饭 Vol.01.cbz"
        existing.write_bytes(b"x")
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        organizer = self.organizer()
        organizer.scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual(item.status, ItemStatus.DUPLICATE)
        existing.unlink()
        organizer.retry([item.id])
        self.assertEqual(self.items.get(item.id).status, ItemStatus.PLANNED)

    def test_missing_library_or_source_dir_refuses_scan_and_execute(self):
        from shutong.engine.organizer import LibraryUnavailable

        organizer, [item], [source] = self.planned("迷宫饭/迷宫饭 Vol.01.zip", policy="delete")
        moved = self.library_dir.with_name("unmounted")
        self.library_dir.rename(moved)
        with self.assertRaises(LibraryUnavailable):
            organizer.execute([item.id])
        with self.assertRaises(LibraryUnavailable):
            organizer.scan(self.library.id)
        self.assertFalse(self.library_dir.exists())
        self.assertTrue(source.exists())
        self.assertEqual(self.items.get(item.id).status, ItemStatus.PLANNED)

    def test_recover_tolerates_io_errors(self):
        organizer, [item], _ = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        with mock.patch("shutong.engine.organizer.Publisher.sweep_staging", side_effect=OSError(5, "EIO")), \
                mock.patch("shutong.engine.organizer.Publisher.recover", side_effect=OSError(5, "EIO")):
            self.organizer().recover()
        self.assertEqual(self.items.get(item.id).status, ItemStatus.PLANNED)

    def test_source_outside_library_does_not_abort_batch(self):
        organizer, items, _ = self.planned("迷宫饭/迷宫饭 Vol.01.zip", "迷宫饭/迷宫饭 Vol.02.zip")
        with self.db.connect() as connection:
            connection.execute("UPDATE items SET source_path = ? WHERE id = ?", ("/elsewhere/x.zip", items[0].id))
        result = organizer.execute([item.id for item in items])
        self.assertEqual(self.items.get(items[1].id).status, ItemStatus.PUBLISHED)
        self.assertEqual(self.items.get(items[0].id).status, ItemStatus.CANCELLED)  # nothing there to build
        self.assertEqual(result["skipped"], 1)

    def test_another_source_of_the_same_volume_is_a_duplicate_not_published(self):
        organizer, [first], _ = self.planned("迷宫饭/迷宫饭 Vol.01.zip")
        organizer.execute([first.id])
        other = self.zip("迷宫饭/迷宫饭 另一版 Vol.01.zip")
        organizer.scan(self.library.id)
        [second] = [item for item in self.all_items() if item.id != first.id]
        self.assertEqual(second.status, ItemStatus.DUPLICATE)
        self.assertEqual(self.items.get(first.id).status, ItemStatus.PUBLISHED)
        self.assertTrue(other.exists())

    def test_claimed_item_keeps_source_even_with_delete_policy(self):
        from shutong.engine.kinds.manga.comicinfo import ComicMetadata, build_comic_info
        from shutong.engine.kinds.manga.volume import VolumeRef
        from decimal import Decimal

        self.library = LibraryStore(self.db).create("删除库", "manga", self.source_dir, self.library_dir,
                                                    source_policy="delete")
        target = self.library_dir / "迷宫饭" / "迷宫饭 Vol.01.cbz"
        target.parent.mkdir()
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("001.jpg", JPEG)
            archive.writestr("ComicInfo.xml", build_comic_info(
                ComicMetadata(series_name="迷宫饭", volume=VolumeRef.volume(Decimal(1))), 1))
        source = self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.organizer().scan(self.library.id)
        [item] = [i for i in self.all_items() if i.library_id == self.library.id]
        self.assertEqual((item.status, item.target_path), (ItemStatus.PUBLISHED, Path("迷宫饭/迷宫饭 Vol.01.cbz")))
        self.assertIn("claimed", [event.kind for event in self.items.events(item.id)])
        self.assertTrue(source.exists())


if __name__ == "__main__":
    unittest.main()
