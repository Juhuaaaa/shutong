import errno
import unittest
from unittest import mock

from shutong.engine.disposal import DisposalContext, dispose_source
from shutong.engine.fingerprint import fingerprint

from .support import EngineTestCase


class DisposalTests(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.arc = self.root / "原档轻小说"
        self.src = self._source("某系列/第1卷.epub", b"epub-1")

    def _source(self, relative, data):
        path = self.source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def ctx(self, policy, archive_dir=None):
        return DisposalContext(policy=policy, source_root=self.source_root, archive_dir=archive_dir)

    def dispose(self, ctx, src):
        return dispose_source(ctx, src, fingerprint(src))

    def test_keep_leaves_source(self):
        self.assertEqual(self.dispose(self.ctx("keep"), self.src).outcome, "kept")
        self.assertTrue(self.src.exists())

    def test_archive_preserves_relative_path(self):
        out = self.dispose(self.ctx("archive", self.arc), self.src)
        self.assertEqual(out.outcome, "archived")
        self.assertEqual(out.destination, self.arc / "某系列" / "第1卷.epub")
        self.assertEqual(out.destination.read_bytes(), b"epub-1")
        self.assertFalse(self.src.exists())

    def test_archive_outside_source_root_uses_file_name(self):
        loose = self.root / "Downloads" / "散落.epub"
        loose.parent.mkdir()
        loose.write_bytes(b"x")
        out = self.dispose(self.ctx("archive", self.arc), loose)
        self.assertEqual(out.destination, self.arc / "散落.epub")

    def test_archive_conflict_leaves_source(self):
        (self.arc / "某系列").mkdir(parents=True)
        (self.arc / "某系列" / "第1卷.epub").write_bytes(b"other")
        self.assertEqual(self.dispose(self.ctx("archive", self.arc), self.src).outcome,
                         "archive_conflict")
        self.assertTrue(self.src.exists())
        self.assertEqual((self.arc / "某系列" / "第1卷.epub").read_bytes(), b"other")

    def test_cross_volume_copy_verifies_before_deleting(self):
        with mock.patch("shutong.engine.disposal._same_volume", return_value=False):
            out = self.dispose(self.ctx("archive", self.arc), self.src)
        self.assertEqual(out.outcome, "archived")
        self.assertEqual(out.destination.read_bytes(), b"epub-1")
        self.assertFalse(self.src.exists())

        src2 = self._source("另一系列/第2卷.epub", b"epub-2")
        arc2 = self.root / "arc2"
        with mock.patch("shutong.engine.disposal._same_volume", return_value=False), \
                mock.patch("shutong.engine.disposal.sha256_file", side_effect=["a", "b"]):
            self.assertEqual(self.dispose(self.ctx("archive", arc2), src2).outcome,
                             "copy_mismatch")
        self.assertTrue(src2.exists())
        self.assertEqual([p for p in arc2.rglob("*") if p.is_file()], [])

    def test_same_device_but_different_mount_falls_back_to_copy(self):
        # Docker bind mounts of one host filesystem share st_dev, yet link/rename give EXDEV.
        from shutong.engine import disposal
        real_move = disposal.no_overwrite_move
        calls = []

        def exdev_once(src, dst):
            calls.append(dst)
            if len(calls) == 1:
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return real_move(src, dst)

        with mock.patch("shutong.engine.disposal._same_volume", return_value=True), \
                mock.patch("shutong.engine.disposal.no_overwrite_move", side_effect=exdev_once):
            out = self.dispose(self.ctx("archive", self.arc), self.src)
        self.assertEqual(out.outcome, "archived")
        self.assertEqual(out.destination.read_bytes(), b"epub-1")
        self.assertFalse(self.src.exists())

    def test_cross_volume_archive_of_image_folder(self):
        folder = self.source_root / "某漫画" / "第01话"
        folder.mkdir(parents=True)
        (folder / "01.jpg").write_bytes(b"1")
        (folder / "02.jpg").write_bytes(b"2")
        with mock.patch("shutong.engine.disposal._same_volume", return_value=False):
            out = self.dispose(self.ctx("archive", self.arc), folder)
        self.assertEqual(out.outcome, "archived")
        self.assertEqual((out.destination / "02.jpg").read_bytes(), b"2")
        self.assertFalse(folder.exists())

    def test_changed_source_is_not_touched(self):
        fp = fingerprint(self.src)
        self.src.write_bytes(b"changed")
        out = dispose_source(self.ctx("delete"), self.src, fp)
        self.assertEqual(out.outcome, "source_changed")
        self.assertTrue(self.src.exists())

    def test_delete_removes_the_source_for_good(self):
        out = self.dispose(self.ctx("delete"), self.src)
        self.assertEqual(out.outcome, "deleted")
        self.assertFalse(self.src.exists())
        self.assertFalse((self.source_root / ".shutong").exists())
        folder = self.source_root / "图片目录"
        folder.mkdir()
        (folder / "01.jpg").write_bytes(b"1")
        self.assertEqual(self.dispose(self.ctx("delete"), folder).outcome, "deleted")
        self.assertFalse(folder.exists())

    def test_missing_source(self):
        fp = fingerprint(self.src)
        self.src.unlink()
        out = dispose_source(self.ctx("delete"), self.src, fp)
        self.assertEqual(out.outcome, "source_missing")

if __name__ == "__main__":
    unittest.main()
