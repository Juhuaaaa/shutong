import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from shutong.engine.fingerprint import fingerprint, sha256_file

MIB = 1024 * 1024


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)

    def test_same_content_same_fingerprint_regardless_of_mtime(self):
        a, b = self.root / "a.zip", self.root / "b.zip"
        a.write_bytes(b"x" * 3_000_000)
        b.write_bytes(b"x" * 3_000_000)
        os.utime(b, (0, 0))
        self.assertEqual(fingerprint(a), fingerprint(b))

    def test_change_in_tail_changes_fingerprint(self):
        a = self.root / "a.zip"
        data = bytearray(b"x" * 3_000_000)
        a.write_bytes(data)
        before = fingerprint(a)
        data[-1] = ord("y")
        a.write_bytes(data)
        self.assertNotEqual(before, fingerprint(a))

    def test_change_in_middle_of_small_file_changes_fingerprint(self):
        a = self.root / "a.epub"
        data = bytearray(b"x" * (MIB + MIB // 2))
        a.write_bytes(data)
        before = fingerprint(a)
        data[MIB] = ord("y")
        a.write_bytes(data)
        self.assertNotEqual(before, fingerprint(a))

    def test_size_is_part_of_fingerprint(self):
        a, b = self.root / "a", self.root / "b"
        a.write_bytes(b"\0" * 10)
        b.write_bytes(b"\0" * 11)
        self.assertNotEqual(fingerprint(a), fingerprint(b))

    def test_small_file_prefix(self):
        small = self.root / "small.cbz"
        small.write_bytes(b"cbz")
        self.assertTrue(fingerprint(small).startswith("v1:f:"))

    def test_directory_ignores_hidden_and_order(self):
        d1, d2 = self.root / "d1", self.root / "d2"
        d1.mkdir()
        d2.mkdir()
        (d1 / "02.jpg").write_bytes(b"two")
        (d1 / "01.jpg").write_bytes(b"one")
        (d1 / ".DS_Store").write_bytes(b"junk")
        (d2 / "01.jpg").write_bytes(b"one")
        (d2 / "02.jpg").write_bytes(b"two")
        self.assertTrue(fingerprint(d1).startswith("v1:d:"))
        self.assertEqual(fingerprint(d1), fingerprint(d2))
        (d2 / "03.jpg").write_bytes(b"three")
        self.assertNotEqual(fingerprint(d1), fingerprint(d2))

    def test_sha256_file_matches_hashlib(self):
        a = self.root / "a"
        a.write_bytes(os.urandom(MIB * 2 + 7))
        self.assertEqual(sha256_file(a), hashlib.sha256(a.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
