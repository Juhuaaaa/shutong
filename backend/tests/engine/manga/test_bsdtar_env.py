import os
from pathlib import Path
import shutil
import sys
import tempfile
import unicodedata
import unittest
from unittest import mock

from shutong.engine.kinds.manga import cbz


class BsdtarLocationTests(unittest.TestCase):
    def test_the_bundled_one_comes_first(self):
        with mock.patch.dict(os.environ, {"SHUTONG_BSDTAR": "/app/bin/bsdtar"}):
            self.assertEqual(cbz._bsdtar(), "/app/bin/bsdtar")

    def test_without_it_the_path_is_searched(self):
        env = {key: value for key, value in os.environ.items() if key != "SHUTONG_BSDTAR"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("shutil.which", return_value="/usr/bin/bsdtar"):
            self.assertEqual(cbz._bsdtar(), "bsdtar")


FIXTURES = Path(__file__).resolve().parents[4] / "desktop" / "smoke" / "fixtures"
SYSTEM_LIBRARY = "/usr/lib/libarchive.2.dylib"  # macOS; on Windows the build points LIBARCHIVE at its own copy


def _load_libarchive():
    if "LIBARCHIVE" not in os.environ and sys.platform == "darwin":
        os.environ["LIBARCHIVE"] = SYSTEM_LIBRARY
    try:
        import libarchive  # noqa: F401
    except Exception:
        return False
    return True


@unittest.skipUnless(_load_libarchive(), "needs libarchive-c and a libarchive library")
class LibarchiveTests(unittest.TestCase):
    """Windows: every bsdtar build crashes on non-ASCII member names and its arguments go through the system
    code page, so the desktop app reads archives through the library's wide-character API instead."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        patcher = mock.patch.object(cbz, "_USE_LIBARCHIVE", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def copy(self, fixture, name="ガンダム 第1卷 👋"):
        path = self.root / (name + Path(fixture).suffix)
        shutil.copy(FIXTURES / fixture, path)
        return path

    def names(self, pages):
        return sorted(unicodedata.normalize("NFC", page.name) for page in pages)

    def test_reads_pages_of_a_non_ascii_archive(self):
        pages = cbz.collect_archive_pages(self.copy("unicode.7z"), self.root)
        self.assertEqual(self.names(pages), ["ガンダム/02.jpg", "第01页.jpg"])
        self.assertEqual({page.path.read_bytes()[:3] for page in pages}, {b"\xff\xd8\xff"})

    def test_no_external_program_is_involved(self):
        with mock.patch.object(cbz.subprocess, "Popen", side_effect=AssertionError("no process")), \
                mock.patch.object(cbz.subprocess, "run", side_effect=AssertionError("no process")):
            cbz.collect_archive_pages(self.copy("unicode.7z"), self.root)

    def test_limits_apply_before_anything_is_extracted(self):
        archive = self.copy("unicode.7z")
        work = self.root / "work"
        work.mkdir()
        with self.assertRaisesRegex(ValueError, "too many files"):
            cbz.collect_archive_pages(archive, work, cbz.ArchiveLimits(max_files=1))
        self.assertEqual(list(work.iterdir()), [])

    def test_a_single_file_over_the_limit_is_refused(self):
        with self.assertRaisesRegex(ValueError, "file size limit"):
            cbz.collect_archive_pages(self.copy("rar5.rar"), self.root, cbz.ArchiveLimits(max_file_bytes=10))

    def test_a_symbolic_link_inside_is_refused(self):
        with self.assertRaisesRegex(ValueError, "link or special"):
            cbz.collect_archive_pages(self.copy("rar4-plain.rar"), self.root)

    def test_a_hard_link_inside_is_refused(self):
        with self.assertRaisesRegex(ValueError, "link or special"):
            cbz.collect_archive_pages(self.copy("rar5-unicode.rar"), self.root)

    def test_an_archive_without_images_says_so(self):
        with self.assertRaisesRegex(Exception, "no valid images"):
            cbz.collect_archive_pages(self.copy("rar5.rar"), self.root)

    def test_a_broken_archive_is_an_error_not_a_crash(self):
        path = self.root / "坏的.rar"
        path.write_bytes(b"this is not an archive at all" * 50)
        with self.assertRaises(Exception):
            cbz.collect_archive_pages(path, self.root)

    def test_the_library_being_absent_is_a_clear_error(self):
        with mock.patch.dict(sys.modules, {"libarchive": None}), self.assertRaisesRegex(Exception, "libarchive"):
            cbz.collect_archive_pages(self.copy("unicode.7z"), self.root)
