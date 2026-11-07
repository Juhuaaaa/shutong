from dataclasses import replace
from decimal import Decimal
import os
from pathlib import Path
import unittest
from unittest import mock
import zipfile

from PIL import Image

from shutong.engine.ai_recognize import FileReading
from shutong.engine.kinds.base import BuildError, SourceEntry
from shutong.engine.kinds.manga.adapter import MangaAdapter, default_relative_target
from shutong.engine.kinds.manga.comicinfo import ComicMetadata, read_comic_info
from shutong.engine.kinds.manga.volume import VolumeRef
from shutong.engine.publish import Publisher
from shutong.store.journal import JournalStore

from ..support import EngineTestCase

JPEG = b"\xff\xd8\xffsynthetic-jpeg"
PNG = b"\x89PNG\r\n\x1a\nsynthetic-png"


class MangaAdapterTests(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.adapter = MangaAdapter()
        self.meta = ComicMetadata(series_name="某漫画", volume=VolumeRef.volume(Decimal(1)))

    def _file(self, relative, data=b"x"):
        path = self.source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _zip(self, relative, members):
        path = self.source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        return path

    def _pdf(self, relative):
        path = self.source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (40, 60), "red").save(
            path, "PDF", save_all=True, append_images=[Image.new("RGB", (40, 60), "blue")]
        )
        return path

    def test_scan_kinds_and_series_folder(self):
        self._zip("间谍过家家[东立电子版]/Vol.01.zip", {"01.jpg": JPEG})
        self._file("某漫画/第01话/01.jpg", JPEG)
        self._file("某漫画/第01话/02.jpg", JPEG)
        self._pdf("单本 Vol.03.pdf")
        self._file("说明.txt", b"text")
        result = self.adapter.scan(self.source_root)
        self.assertEqual(
            [(entry.kind, entry.series_folder, entry.path.name) for entry in result.entries],
            [("pdf", None, "单本 Vol.03.pdf"),
             ("folder", "某漫画", "第01话"),
             ("archive", "间谍过家家[东立电子版]", "Vol.01.zip")],
        )
        self.assertEqual(result.skipped, ())

    def test_scan_never_enters_hidden_or_trash(self):
        self._zip(".shutong/trash/20261029/x/Vol.01.zip", {"01.jpg": JPEG})
        self._zip(".cache/a.zip", {"01.jpg": JPEG})
        self._file("系列/.hidden.zip", b"x")
        self.assertEqual(self.adapter.scan(self.source_root).entries, ())

    def test_folder_with_archives_is_not_an_image_folder(self):
        self._file("系列/cover.jpg", JPEG)
        self._zip("系列/Vol.01.zip", {"01.jpg": JPEG})
        entries = self.adapter.scan(self.source_root).entries
        self.assertEqual([entry.kind for entry in entries], ["archive"])

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_scan_reports_symlinks(self):
        target = self._zip("真/Vol.01.zip", {"01.jpg": JPEG})
        (self.source_root / "链接.zip").symlink_to(target)
        result = self.adapter.scan(self.source_root)
        self.assertEqual([(s.path.name, s.reason) for s in result.skipped], [("链接.zip", "symlink")])
        self.assertEqual([entry.path.name for entry in result.entries], ["Vol.01.zip"])

    def test_volume_from_ai(self):
        def reading(unit, number, end=None, label=""):
            return FileReading(unit, None if number is None else Decimal(number),
                               None if end is None else Decimal(end), label, 0.9)

        self.assertEqual(self.adapter.volume_from_ai(reading("volume", "19")).key(), "volume:19")
        self.assertEqual(self.adapter.volume_from_ai(reading("volume", "1", "5")).key(), "range:1-5")
        self.assertEqual(self.adapter.volume_from_ai(reading("volume", "3", "3")).key(), "volume:3")
        self.assertEqual(self.adapter.volume_from_ai(reading("chapter", "171")).key(), "chapter:171")
        self.assertEqual(self.adapter.volume_from_ai(reading("chapter", "1", "40")).key(), "chapter:1-40")
        special = self.adapter.volume_from_ai(reading("special", "2", label="画集"))
        self.assertEqual((special.key(), special.label), ("special:2", "画集"))
        self.assertEqual(self.adapter.volume_from_ai(reading("special", None)).key(), "special:1")
        self.assertIsNone(self.adapter.volume_from_ai(reading("volume", None)))
        self.assertEqual(self.adapter.facts(SourceEntry(self.source_root / "x.zip", "archive", None)), {})

    def test_build_and_verify_each_kind_through_publisher(self):
        entries = [
            SourceEntry(self._zip("某漫画/Vol.01.zip", {"b/2.jpg": JPEG, "b/1.png": PNG}), "archive", "某漫画"),
            SourceEntry(self._pdf("某漫画/Vol.01.pdf"), "pdf", "某漫画"),
            SourceEntry(self._file("某漫画/第01话/01.jpg", JPEG).parent, "folder", "某漫画"),
        ]
        publisher = Publisher(JournalStore(self.db))
        for number, entry in enumerate(entries):
            with self.subTest(kind=entry.kind):
                item = self.make_item("{0}.src".format(number))
                meta = replace(self.meta, volume=VolumeRef.volume(Decimal(number + 1)))
                final = self.lib / default_relative_target("某漫画", meta.volume)
                staged = publisher.start(item, self.lib, final)
                pages = self.adapter.build(entry, meta, staged)
                result = publisher.commit(item, verify=lambda path: self.adapter.verify(path, meta))
                fields = read_comic_info(result.final_path)
                self.assertEqual(fields["Series"], "某漫画")
                self.assertEqual(fields["Volume"], str(number + 1))
                self.assertEqual(fields["PageCount"], str(pages))
                self.assertGreater(pages, 0)

    def test_verify_rejects_wrong_series_and_volume(self):
        staged = self.root / "out.cbz"
        entry = SourceEntry(self._zip("某漫画/Vol.01.zip", {"01.jpg": JPEG}), "archive", "某漫画")
        self.adapter.build(entry, self.meta, staged)
        self.adapter.verify(staged, self.meta)
        with self.assertRaises(BuildError):
            self.adapter.verify(staged, replace(self.meta, series_name="别的"))
        with self.assertRaises(BuildError):
            self.adapter.verify(staged, replace(self.meta, volume=VolumeRef.volume(Decimal(2))))
        with self.assertRaises(BuildError):
            self.adapter.verify(staged, replace(self.meta, volume=VolumeRef.special(1)))

    def test_verify_special_and_range(self):
        for volume in (VolumeRef.special(2, "番外"), VolumeRef.range(Decimal(1), Decimal(5))):
            with self.subTest(volume=volume.key()):
                staged = self.root / "{0}.cbz".format(volume.kind)
                entry = SourceEntry(self._zip("某漫画/x.zip", {"01.jpg": JPEG}), "archive", "某漫画")
                meta = replace(self.meta, volume=volume)
                self.adapter.build(entry, meta, staged)
                self.adapter.verify(staged, meta)

    def test_failed_build_leaves_no_staged_file(self):
        broken = self._file("某漫画/Vol.01.zip", b"PK\x03\x04garbage")
        staged = self.root / "out.cbz"
        with self.assertRaises(BuildError):
            self.adapter.build(SourceEntry(broken, "archive", "某漫画"), self.meta, staged)
        self.assertFalse(staged.exists())

    def test_default_target_matches_legacy_naming(self):
        self.assertEqual(
            default_relative_target("间谍过家家[东立电子版]", VolumeRef.volume(Decimal("1.5"))),
            Path("间谍过家家[东立电子版]") / "间谍过家家[东立电子版] Vol.01.5.cbz",
        )

    def test_keep_pdf_publishes_pdf_unchanged(self):
        adapter = MangaAdapter(pdf_to_cbz=False)
        entry = SourceEntry(self._pdf("某漫画/Vol.03.pdf"), "pdf", "某漫画")
        self.assertEqual(adapter.output_suffix(entry), ".pdf")
        meta = replace(self.meta, volume=VolumeRef.volume(Decimal(3)))
        final = self.lib / default_relative_target("某漫画", meta.volume, suffix=".pdf")
        publisher = Publisher(JournalStore(self.db))
        item = self.make_item()
        staged = publisher.start(item, self.lib, final)
        self.assertEqual(adapter.build(entry, meta, staged), 2)
        result = publisher.commit(item, verify=lambda path: adapter.verify(path, meta))
        self.assertEqual(result.final_path.name, "某漫画 Vol.03.pdf")
        self.assertEqual(result.final_path.read_bytes(), entry.path.read_bytes())

    def test_keep_pdf_rejects_unreadable_pdf(self):
        broken = SourceEntry(self._file("某漫画/坏.pdf", b"not a pdf"), "pdf", "某漫画")
        staged = self.root / "out.pdf"
        with self.assertRaises(BuildError):
            MangaAdapter(pdf_to_cbz=False).build(broken, self.meta, staged)
        self.assertFalse(staged.exists())

    def test_archives_still_become_cbz_when_pdf_kept(self):
        adapter = MangaAdapter(pdf_to_cbz=False)
        self.assertEqual(adapter.output_suffix(SourceEntry(Path("a.zip"), "archive", None)), ".cbz")
        self.assertEqual(MangaAdapter().output_suffix(SourceEntry(Path("a.pdf"), "pdf", None)), ".cbz")

    def test_verify_wraps_truncated_cbz(self):
        staged = self.root / "out.cbz"
        entry = SourceEntry(self._zip("某漫画/Vol.01.zip", {"01.jpg": JPEG}), "archive", "某漫画")
        self.adapter.build(entry, self.meta, staged)
        staged.write_bytes(staged.read_bytes()[:40])
        with self.assertRaises(BuildError):
            self.adapter.verify(staged, self.meta)

    def test_keep_pdf_copy_failure_leaves_nothing(self):
        entry = SourceEntry(self._pdf("某漫画/Vol.03.pdf"), "pdf", "某漫画")
        staged = self.root / "out.pdf"

        def partial_copy(source, target):
            Path(target).write_bytes(b"%PDF-partial")
            raise OSError(28, "No space left on device")

        with mock.patch("shutong.engine.kinds.manga.adapter.shutil.copyfile", side_effect=partial_copy):
            with self.assertRaises(BuildError):
                MangaAdapter(pdf_to_cbz=False).build(entry, self.meta, staged)
        self.assertFalse(staged.exists())

if __name__ == "__main__":
    unittest.main()
