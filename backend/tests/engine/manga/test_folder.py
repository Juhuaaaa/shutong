import os
from pathlib import Path
import tempfile
import unittest

from shutong.engine.kinds.base import BuildError
from shutong.engine.kinds.manga.folder import collect_folder_pages

JPEG = b"\xff\xd8\xffsynthetic-jpeg"
PNG = b"\x89PNG\r\n\x1a\nsynthetic-png"


class FolderPagesTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.folder = Path(self._directory.name) / "第01话"
        self.folder.mkdir()

    def _write(self, name, data):
        (self.folder / name).write_bytes(data)

    def test_natural_order_and_junk_ignored(self):
        self._write("10.jpg", JPEG)
        self._write("2.jpg", JPEG)
        self._write("1.png", PNG)
        self._write("Thumbs.db", b"junk")
        self._write(".DS_Store", JPEG)
        self._write("说明.txt", "不是图片".encode("utf-8"))
        pages = collect_folder_pages(self.folder)
        self.assertEqual([page.name for page in pages], ["1.png", "2.jpg", "10.jpg"])
        self.assertEqual([page.extension for page in pages], [".png", ".jpg", ".jpg"])
        self.assertEqual(pages[0].path, self.folder / "1.png")

    def test_content_decides_image_not_extension(self):
        self._write("01.dat", PNG)
        self._write("02.jpg", b"not really")
        pages = collect_folder_pages(self.folder)
        self.assertEqual([(page.name, page.extension) for page in pages], [("01.dat", ".png")])

    def test_folder_without_images_fails(self):
        self._write("说明.txt", b"text")
        with self.assertRaises(BuildError):
            collect_folder_pages(self.folder)

    def test_subdirectories_are_not_descended(self):
        (self.folder / "sub").mkdir()
        (self.folder / "sub" / "01.jpg").write_bytes(JPEG)
        self._write("02.jpg", JPEG)
        self.assertEqual([page.name for page in collect_folder_pages(self.folder)], ["02.jpg"])

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "needs POSIX permissions as a non-root user")
    def test_unreadable_image_is_build_error(self):
        self._write("01.jpg", JPEG)
        locked = self.folder / "01.jpg"
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o644)
        with self.assertRaises(BuildError):
            collect_folder_pages(self.folder)


if __name__ == "__main__":
    unittest.main()
