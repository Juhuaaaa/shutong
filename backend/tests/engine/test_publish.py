import errno
import hashlib
import os
import unittest
from unittest import mock

from shutong.engine.publish import (
    InvalidTargetName,
    Publisher,
    TargetExists,
    no_overwrite_move,
    validate_target,
)
from shutong.store.journal import JournalStore

from .support import EngineTestCase


def _fail(error):
    def verify(path):
        raise error
    return verify


class PublishTests(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.journal = JournalStore(self.db)
        self.pub = Publisher(self.journal)
        self.final = self.lib / "间谍过家家" / "间谍过家家 Vol.19.cbz"

    def test_overwrite_replaces_the_target_only_after_verifying(self):
        self.final.parent.mkdir(parents=True)
        self.final.write_bytes(b"old")
        item = self.make_item()
        staged = self.pub.start(item, self.lib, self.final, overwrite=True)
        staged.write_bytes(b"new")
        with self.assertRaises(ValueError):
            self.pub.commit(item, verify=_fail(ValueError("bad")), overwrite=True)
        self.assertEqual(self.final.read_bytes(), b"old")
        staged = self.pub.start(item, self.lib, self.final, overwrite=True)
        staged.write_bytes(b"new")
        result = self.pub.commit(item, verify=lambda path: None, overwrite=True)
        self.assertEqual((self.final.read_bytes(), result.method), (b"new", "replace"))
        self.assertFalse(staged.exists())

    def test_publishes_and_marks_journal(self):
        item = self.make_item()
        staged = self.pub.start(item, self.lib, self.final)
        self.assertEqual(staged.parent, self.lib / ".shutong" / "staging")
        staged.write_bytes(b"cbz")
        result = self.pub.commit(item, verify=lambda path: None)
        self.assertEqual(result.final_path, self.final)
        self.assertEqual(self.final.read_bytes(), b"cbz")
        self.assertFalse(staged.exists())
        self.assertEqual(self.journal.get(item).phase, "published")
        self.assertEqual(result.sha256, hashlib.sha256(b"cbz").hexdigest())
        self.assertEqual(result.size, 3)
        self.assertIn(result.method, {"link", "rename", "fallback"})

    def test_existing_target_is_never_overwritten(self):
        self.final.parent.mkdir(parents=True)
        self.final.write_bytes(b"old")
        with self.assertRaises(TargetExists):
            self.pub.start(self.make_item("a.zip"), self.lib, self.final)

        other = self.lib / "间谍过家家" / "间谍过家家 Vol.20.cbz"
        item = self.make_item("b.zip")
        staged = self.pub.start(item, self.lib, other)
        staged.write_bytes(b"new")
        other.write_bytes(b"old")  # target appears after start: a race
        with self.assertRaises(TargetExists):
            self.pub.commit(item, verify=lambda path: None)
        self.assertEqual(other.read_bytes(), b"old")
        self.assertFalse(staged.exists())
        self.assertIsNone(self.journal.get(item))

    def test_case_only_difference_counts_as_existing(self):
        (self.lib / "vol.01.cbz").write_bytes(b"old")
        if not (self.lib / "VOL.01.CBZ").exists():
            self.skipTest("case-sensitive filesystem")
        with self.assertRaises(TargetExists):
            self.pub.start(self.make_item(), self.lib, self.lib / "Vol.01.cbz")

    def test_case_only_race_is_not_overwritten(self):
        probe = self.lib / "probe"
        probe.write_bytes(b"")
        if not (self.lib / "PROBE").exists():
            self.skipTest("case-sensitive filesystem")
        item = self.make_item()
        staged = self.pub.start(item, self.lib, self.lib / "Vol.01.cbz")
        staged.write_bytes(b"new")
        (self.lib / "vol.01.cbz").write_bytes(b"old")
        with self.assertRaises(TargetExists):
            self.pub.commit(item, verify=lambda path: None)
        self.assertEqual((self.lib / "vol.01.cbz").read_bytes(), b"old")

    def test_verify_failure_cleans_up(self):
        item = self.make_item()
        staged = self.pub.start(item, self.lib, self.final)
        staged.write_bytes(b"bad")
        with self.assertRaises(ValueError):
            self.pub.commit(item, verify=_fail(ValueError("broken")))
        self.assertFalse(staged.exists())
        self.assertFalse(self.final.exists())
        self.assertIsNone(self.journal.get(item))
        # the item can be retried from scratch
        staged = self.pub.start(item, self.lib, self.final)
        staged.write_bytes(b"good")
        self.pub.commit(item, verify=lambda path: None)
        self.assertEqual(self.final.read_bytes(), b"good")

    def test_abort_removes_staging(self):
        item = self.make_item()
        staged = self.pub.start(item, self.lib, self.final)
        staged.write_bytes(b"partial")
        self.pub.abort(item)
        self.assertFalse(staged.exists())
        self.assertIsNone(self.journal.get(item))
        self.pub.abort(item)  # idempotent

    def test_rejects_windows_illegal_names_everywhere(self):
        for name in ["a:b.cbz", "CON.cbz", "nul", "com1.txt", "trailing.", "space ", "q?.cbz",
                     "tab\t.cbz", 'quote".cbz', "pipe|.cbz"]:
            with self.subTest(name=name), self.assertRaises(InvalidTargetName):
                validate_target(self.lib, self.lib / "系列" / name)
        with self.assertRaises(InvalidTargetName):
            validate_target(self.lib, self.lib / "AUX" / "Vol.01.cbz")
        validate_target(self.lib, self.lib / "系列[东立扫图版]" / "系列 Vol.01.5.cbz")

    def test_rejects_trailing_dot_even_when_abspath_strips_it(self):
        # Windows abspath() drops trailing dots/spaces from every component.
        real_abspath = os.path.abspath

        def windows_like(path):
            return os.sep.join(part.rstrip(". ") or part
                               for part in real_abspath(path).split(os.sep))

        with mock.patch("shutong.engine.publish.os.path.abspath", side_effect=windows_like):
            for name in ["trailing.", "space "]:
                with self.subTest(name=name), self.assertRaises(InvalidTargetName):
                    validate_target(self.lib, self.lib / "系列" / name)

    def test_rejects_escape_and_staging_area(self):
        for final in [self.lib / ".." / "x.cbz", self.lib / ".shutong" / "x.cbz", self.root / "x.cbz",
                      self.lib]:
            with self.subTest(final=final), self.assertRaises(InvalidTargetName):
                validate_target(self.lib, final)

    def test_falls_back_when_hardlinks_unsupported(self):
        if os.name == "nt":
            self.skipTest("posix only")
        src, dst = self.root / "src", self.lib / "sub" / "dst"
        src.write_bytes(b"data")
        with mock.patch("shutong.engine.publish.os.link",
                        side_effect=OSError(errno.EPERM, "no links")):
            self.assertEqual(no_overwrite_move(src, dst), "fallback")
        self.assertEqual(dst.read_bytes(), b"data")
        self.assertFalse(src.exists())

    def test_fallback_still_refuses_existing_target(self):
        src, dst = self.root / "src", self.lib / "dst"
        src.write_bytes(b"new")
        dst.write_bytes(b"old")
        with mock.patch("shutong.engine.publish.os.link",
                        side_effect=OSError(errno.EPERM, "no links")):
            with self.assertRaises(TargetExists):
                no_overwrite_move(src, dst)
        self.assertEqual(dst.read_bytes(), b"old")
        self.assertTrue(src.exists())

    def test_move_directory(self):
        src = self.root / "folder"
        src.mkdir()
        (src / "01.jpg").write_bytes(b"1")
        dst = self.lib / "moved"
        no_overwrite_move(src, dst)
        self.assertEqual((dst / "01.jpg").read_bytes(), b"1")
        self.assertFalse(src.exists())


if __name__ == "__main__":
    unittest.main()
