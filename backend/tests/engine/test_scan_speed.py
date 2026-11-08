"""A scan of a big, mostly organized source folder reads only files that are new or changed."""
import os
from unittest import mock

from shutong.engine import organizer as organizer_module
from shutong.engine.fingerprint import fingerprint as real_fingerprint
from shutong.engine.states import ItemStatus

from .test_organizer_scan import OrganizerFixture


class ScanSpeedTests(OrganizerFixture):
    def scan_counting(self):
        reads = []

        def counting(path):
            reads.append(path.name)
            return real_fingerprint(path)

        with mock.patch.object(organizer_module, "fingerprint", counting):
            self.organizer().scan(self.library.id)
        return reads

    def test_unchanged_files_are_not_read_again(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("迷宫饭/迷宫饭 Vol.02.zip")
        self.assertEqual(sorted(self.scan_counting()), ["迷宫饭 Vol.01.zip", "迷宫饭 Vol.02.zip"])
        self.assertEqual(self.scan_counting(), [])

    def test_a_changed_file_is_read_again(self):
        path = self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.scan_counting()
        with open(path, "ab") as handle:  # same name, new bytes
            handle.write(b"more")
        self.assertEqual(self.scan_counting(), ["迷宫饭 Vol.01.zip"])
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))  # touched only
        self.assertEqual(self.scan_counting(), ["迷宫饭 Vol.01.zip"])

    def test_a_new_file_beside_known_ones_is_found(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.scan_counting()
        self.zip("迷宫饭/迷宫饭 Vol.02.zip")
        self.assertEqual(self.scan_counting(), ["迷宫饭 Vol.02.zip"])
        self.assertEqual(sorted(item.status for item in self.all_items()), [ItemStatus.PLANNED, ItemStatus.PLANNED])

    def test_a_renamed_file_is_followed_without_a_new_item(self):
        path = self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.scan_counting()
        moved = path.with_name("迷宫饭 第1卷.zip")
        path.rename(moved)
        self.assertEqual(self.scan_counting(), ["迷宫饭 第1卷.zip"])  # a new path is read once
        [item] = self.all_items()
        self.assertEqual(item.source_path, moved)


class ForgetTests(OrganizerFixture):
    def test_files_gone_from_the_source_are_forgotten(self):
        kept = self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        gone = self.zip("迷宫饭/迷宫饭 Vol.02.zip")
        self.organizer().scan(self.library.id)
        gone.unlink()
        self.organizer().scan(self.library.id)
        with self.db.connect() as connection:
            paths = [row[0] for row in connection.execute("SELECT path FROM fingerprint_cache")]
        self.assertEqual(paths, [str(kept)])


class PreloadTests(OrganizerFixture):
    def test_known_files_are_told_apart_without_a_query_each(self):
        for n in range(1, 4):
            self.zip("迷宫饭/迷宫饭 Vol.0{0}.zip".format(n))
        self.organizer().scan(self.library.id)
        from shutong.store.fingerprints import FingerprintCache
        from shutong.store.records import ItemStore
        with mock.patch.object(FingerprintCache, "lookup", side_effect=AssertionError("one query per file")), \
                mock.patch.object(ItemStore, "find_by_fingerprint", side_effect=AssertionError("one query per file")):
            self.organizer().scan(self.library.id)
        self.assertEqual([item.status for item in self.all_items()], [ItemStatus.PLANNED] * 3)

    def test_a_copy_in_another_folder_in_the_same_scan_is_known(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        first = self.source_dir / "迷宫饭" / "迷宫饭 Vol.01.zip"
        copy = self.source_dir / "备份" / "迷宫饭 Vol.01.zip"
        copy.parent.mkdir()
        copy.write_bytes(first.read_bytes())
        self.organizer().scan(self.library.id)
        self.assertEqual(len(self.all_items()), 1)
