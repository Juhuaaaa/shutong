"""An item may live outside the library's source dir: dropped files stay where the user keeps them."""
from pathlib import Path
import unicodedata

from shutong.engine.fingerprint import fingerprint
from shutong.engine.organizer import entry_for, review_group, _name_in_folder
from shutong.engine.kinds.base import SourceEntry
from shutong.store.records import LibraryStore

from .test_organizer_scan import OrganizerFixture


class SourceRootTests(OrganizerFixture):
    def setUp(self):
        super().setUp()
        self.elsewhere = self.root / "elsewhere"

    def test_entry_outside_source_dir_uses_its_root(self):
        path = self.elsewhere / "迷宫饭" / "迷宫饭 Vol.01.zip"
        entry = entry_for(self.library, path, root=self.elsewhere)
        self.assertEqual((entry.series_folder, entry.root), ("迷宫饭", self.elsewhere))

    def test_entry_without_root_still_needs_the_source_dir(self):
        with self.assertRaises(ValueError):
            entry_for(self.library, self.elsewhere / "a.zip")

    def test_review_group_uses_root(self):
        self.assertEqual(review_group(self.library, self.elsewhere / "迷宫饭" / "1.zip", root=self.elsewhere), "迷宫饭")
        self.assertEqual(review_group(self.library, self.elsewhere / "1.zip", root=self.elsewhere), "1.zip")
        self.assertEqual(review_group(self.library, self.source_dir / "1.zip"), "1.zip")

    def test_loose_dropped_file_reads_its_folder(self):
        self.assertEqual(entry_for(self.library, self.elsewhere / "1.zip", root=self.elsewhere).series_folder, "elsewhere")
        self.assertIsNone(entry_for(self.library, self.source_dir / "1.zip").series_folder)
        self.assertIsNone(entry_for(self.library, Path("/1.zip"), root=Path("/")).series_folder)

    def test_name_in_folder_uses_the_entrys_root(self):
        entry = SourceEntry(self.elsewhere / "迷宫饭" / "1.zip", "archive", "迷宫饭", self.elsewhere)
        self.assertEqual(_name_in_folder(self.library, entry), "1.zip")

    def test_root_spelled_in_another_unicode_form_still_matches(self):
        # locate_source can respell a parent folder: macOS writes names decomposed, the root may be composed.
        decomposed = unicodedata.normalize("NFD", "ガンダム")
        composed_root = self.elsewhere / unicodedata.normalize("NFC", "ガンダム")
        entry = entry_for(self.library, self.elsewhere / decomposed / "A" / "1.zip", root=composed_root)
        self.assertEqual(entry.series_folder, "A")

    def test_item_remembers_its_root(self):
        item = self.items.create(self.library.id, self.elsewhere / "a.zip", "v1:a", source_root=self.elsewhere)
        self.assertEqual(item.source_root, self.elsewhere)
        self.assertFalse(item.originals_kept)
        self.assertIsNone(self.items.create(self.library.id, self.source_dir / "b.zip", "v1:b").source_root)

    def _managed_item(self, path, root):
        library = LibraryStore(self.db).create("托管", "manga", "", self.library_dir, source_policy="keep")
        return library, self.items.create(library.id, path, fingerprint(path), source_root=root)

    def test_dropped_item_is_kept_even_in_managed_library(self):
        path = self.elsewhere / "a.zip"
        path.parent.mkdir()
        path.write_bytes(b"data")
        library, item = self._managed_item(path, self.elsewhere)
        self.organizer()._dispose(library, item)
        self.assertTrue(path.exists())
        self.assertEqual(self.items.events(item.id)[-1].detail["outcome"], "kept")

    def test_dropped_item_is_kept_whatever_the_library_policy_says(self):
        path = self.elsewhere / "a.zip"
        path.parent.mkdir()
        path.write_bytes(b"data")
        library = LibraryStore(self.db).create("删除", "manga", "", self.library_dir, source_policy="delete")
        item = self.items.create(library.id, path, fingerprint(path), source_root=self.elsewhere)
        self.organizer()._dispose(library, item)
        self.assertTrue(path.exists())

    def test_upload_in_managed_library_is_still_deleted(self):
        library = LibraryStore(self.db).create("托管", "manga", "", self.library_dir, source_policy="keep")
        path = Path(library.source_dir) / "a.zip"
        path.write_bytes(b"data")
        item = self.items.create(library.id, path, fingerprint(path))
        self.organizer()._dispose(library, item)
        self.assertFalse(path.exists())
