"""Names and failures a Windows user will meet: the item ends up readable, never crashes, never half written."""
import errno
from unittest import mock
import os

from shutong.engine import publish
from shutong.engine.publish import InvalidTargetName, validate_target
from shutong.engine.states import ItemStatus

from .reader_ai import ReaderAi
from .test_match import subject
from .test_organizer_scan import OrganizerFixture


class NamesTests(OrganizerFixture):
    def run_title(self, title):
        self.zip("书/书 Vol.01.zip")
        special = subject(1, title, total=1)
        organizer = self.organizer(ai=ReaderAi(series={"书": {"title": title}}), source=type(self.source)([special], subjects={1: special}))
        organizer.scan(self.library.id, on_planned=organizer.execute)
        return self.all_items()[0]

    def test_title_with_a_colon_becomes_full_width(self):
        item = self.run_title("Re:从零开始")
        self.assertEqual(item.status, ItemStatus.PUBLISHED, item.error)
        self.assertEqual(item.target_path.parts[0], "Re：从零开始")

    def test_title_ending_in_a_dot_is_still_organized(self):
        item = self.run_title("这样的我...")
        self.assertEqual(item.status, ItemStatus.PUBLISHED, item.error)
        self.assertFalse(item.target_path.parts[0].endswith("."))

    def test_reserved_name_title_is_still_organized(self):
        item = self.run_title("CON")
        self.assertEqual(item.status, ItemStatus.PUBLISHED, item.error)
        validate_target(self.library_dir, self.library_dir / item.target_path)


class NovelNamesTests(OrganizerFixture):
    def test_light_novel_title_with_a_colon_and_a_dot(self):
        from shutong.store.records import LibraryStore
        from zipfile import ZipFile
        library = LibraryStore(self.db).create("轻小说", "novel", self.source_dir, self.library_dir)
        path = self.source_dir / "书" / "书 Vol.01.epub"
        path.parent.mkdir()
        with ZipFile(path, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip")
        title = "Re:从零开始..."
        special = subject(1, title, total=1)
        organizer = self.organizer(ai=ReaderAi(series={"书": {"title": title}}), source=type(self.source)([special], subjects={1: special}))
        organizer.scan(library.id, on_planned=None)
        item = self.all_items()[0]
        self.assertNotEqual(item.status, ItemStatus.FAILED, item.error)
        if item.target_path is not None:
            validate_target(self.library_dir, self.library_dir / item.target_path)


class LongPathTests(OrganizerFixture):
    def test_long_target_rejected_where_the_system_limits_it(self):
        final = self.library_dir / ("书" * 100) / ("书" * 100) / ("书" * 100)
        with mock.patch.object(publish, "_MAX_PATH", 260), self.assertRaises(InvalidTargetName) as caught:
            validate_target(self.library_dir, final)
        self.assertIn("库目录太深", str(caught.exception))

    def test_no_limit_elsewhere(self):
        if os.name != "nt":
            validate_target(self.library_dir, self.library_dir / ("书" * 100) / ("书" * 100) / ("书" * 100))

    def test_too_long_target_fails_with_a_readable_reason(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        organizer = self.organizer()
        with mock.patch.object(publish, "_MAX_PATH", 20):
            organizer.scan(self.library.id, on_planned=organizer.execute)
        item = self.all_items()[0]
        self.assertEqual(item.status, ItemStatus.FAILED)
        self.assertIn("库目录太深", item.error)


class FailureTests(OrganizerFixture):
    def build_raising(self, error):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        organizer = self.organizer()
        with mock.patch("shutong.engine.kinds.manga.adapter.MangaAdapter.build", side_effect=error):
            organizer.scan(self.library.id, on_planned=organizer.execute)
        return self.all_items()[0]

    def leftovers(self):
        return [path for path in self.library_dir.rglob("*") if path.is_file() and path.suffix != ".lock"]

    def test_no_space_is_explained_and_leaves_nothing_behind(self):
        item = self.build_raising(OSError(errno.ENOSPC, "No space left on device"))
        self.assertEqual(item.status, ItemStatus.FAILED)
        self.assertIn("磁盘空间不足", item.error)
        self.assertEqual(self.leftovers(), [])

    def test_locked_target_fails_and_can_be_retried(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        organizer = self.organizer()
        with mock.patch("shutong.engine.publish.no_overwrite_move", side_effect=PermissionError(errno.EACCES, "locked")):
            organizer.scan(self.library.id, on_planned=organizer.execute)
        item = self.all_items()[0]
        self.assertEqual(item.status, ItemStatus.FAILED)
        self.assertIn("权限", item.error)
        organizer.retry([item.id])
        organizer.execute([item.id])
        self.assertEqual(self.items.get(item.id).status, ItemStatus.PUBLISHED)
