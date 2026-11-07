from dataclasses import replace
from decimal import Decimal
import os
from pathlib import Path
import unicodedata
import unittest
import zipfile

from shutong.engine.ai_recognize import FileReading
from shutong.engine.kinds.base import BuildError, SourceEntry
from shutong.engine.kinds.novel.adapter import NovelAdapter, NovelPlan, default_relative_target
from shutong.engine.kinds.novel.epub import KavitaMetadata, read_metadata
from shutong.engine.kinds.novel.naming import NovelVolume
from shutong.engine.publish import Publisher
from shutong.store.journal import JournalStore

from ..support import EngineTestCase
from .test_epub import build_epub

SERIES = "[86-不存在的战区-][安里アサト]"


class NovelAdapterTests(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.adapter = NovelAdapter()

    def _epub(self, relative, **options):
        path = self.source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        build_epub(path, **options)
        return path

    def _file(self, relative, data):
        path = self.source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _entry(self, name, folder=SERIES, **options):
        relative = Path(folder) / name if folder else Path(name)
        return SourceEntry(self._epub(relative, **options), "epub", folder)

    def _plan(self, source, **metadata):
        values = {"series": "86", "series_index": Decimal(1), "title": "Book Title"}
        values.update(metadata)
        return NovelPlan(source, KavitaMetadata(**values))

    def test_scan_finds_epubs_and_skips_temp_hidden(self):
        self._epub(SERIES + "/86 Vol.01.epub")
        self._epub(SERIES + "/sub/86 Vol.02.EPUB")
        self._epub(SERIES + "/~$86.epub")
        self._epub(".shutong/trash/20261029/x.epub")
        self._epub("散本 Vol.3.epub")
        self._file("说明.txt", b"text")
        result = self.adapter.scan(self.source_root)
        self.assertEqual(
            [(entry.kind, entry.series_folder, entry.path.name) for entry in result.entries],
            [("epub", SERIES, "86 Vol.01.epub"),
             ("epub", SERIES, "86 Vol.02.EPUB"),
             ("epub", None, "散本 Vol.3.epub")],
        )

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_scan_reports_symlinks(self):
        target = self._epub(SERIES + "/86 Vol.01.epub")
        (self.source_root / "链接.epub").symlink_to(target)
        result = self.adapter.scan(self.source_root)
        self.assertEqual([(s.path.name, s.reason) for s in result.skipped], [("链接.epub", "symlink")])

    def test_scan_series_folder_is_nfc(self):
        self._epub(unicodedata.normalize("NFD", "[ダンジョン飯]") + "/Vol.01.epub")
        entry = self.adapter.scan(self.source_root).entries[0]
        self.assertEqual(entry.series_folder, unicodedata.normalize("NFC", "[ダンジョン飯]"))

    def test_facts_come_from_the_opf(self):
        facts = self.adapter.facts(self._entry("86 Vol.01.epub", creators=("安里アサト",)))
        self.assertEqual((facts["title"], facts["creators"]), ("Book Title", ("安里アサト",)))
        unreadable = self._file(SERIES + "/86 Vol.02.epub", b"not a zip")
        self.assertEqual(self.adapter.facts(SourceEntry(unreadable, "epub", SERIES)), {})

    def test_volume_from_ai(self):
        def reading(unit, number, end=None):
            return FileReading(unit, None if number is None else Decimal(number),
                               None if end is None else Decimal(end), "", 0.9)

        self.assertEqual(self.adapter.volume_from_ai(reading("volume", "0")), NovelVolume.volume(Decimal(0)))
        self.assertEqual(self.adapter.volume_from_ai(reading("chapter", "2.5")), NovelVolume.volume(Decimal("2.5")))
        self.assertEqual(self.adapter.volume_from_ai(reading("special", None)), NovelVolume.special())
        self.assertIsNone(self.adapter.volume_from_ai(reading("volume", "1", "3")))
        self.assertIsNone(self.adapter.volume_from_ai(reading("volume", None)))

    def test_build_and_verify_through_publisher(self):
        entry = self._entry("86 Vol.01.epub")
        plan = self._plan(entry.path)
        publisher = Publisher(JournalStore(self.db))
        item = self.make_item()
        final = self.lib / default_relative_target("86", NovelVolume.volume(Decimal(1)))
        staged = publisher.start(item, self.lib, final)
        self.assertGreater(self.adapter.build(entry, plan, staged), 0)
        result = publisher.commit(item, verify=lambda path: self.adapter.verify(path, plan))
        self.assertEqual(result.final_path.name, "86 Vol.01.epub")
        metadata = read_metadata(result.final_path)
        self.assertEqual((metadata.series, metadata.series_index), ("86", "1"))

    def test_special_target_and_index(self):
        self.assertEqual(default_relative_target("86", NovelVolume.special(), special_index=2),
                         Path("86") / "86 SP02.epub")

    def test_bad_epub_build_fails_and_leaves_nothing(self):
        no_opf = self.root / "no-opf.epub"
        with zipfile.ZipFile(no_opf, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip")
            archive.writestr("text/ch1.xhtml", "<html/>")
        not_zip = self._file("坏.epub", b"not a zip")
        for source in (not_zip, no_opf):
            with self.subTest(source=source.name):
                staged = self.root / "out-{0}.epub".format(source.stem)
                with self.assertRaises(BuildError):
                    self.adapter.build(SourceEntry(source, "epub", None), self._plan(source), staged)
                self.assertFalse(staged.exists())

    def _rebuild(self, staged, name, *, extra=None, mimetype_compress=zipfile.ZIP_STORED, mimetype_last=False):
        with zipfile.ZipFile(staged) as archive:
            members = [(info, archive.read(info)) for info in archive.infolist()]
        broken = staged.with_name(name + ".epub")
        mimetype = [item for item in members if item[0].filename == "mimetype"]
        others = [item for item in members if item[0].filename != "mimetype"]
        ordered = others + mimetype if mimetype_last else mimetype + others
        with zipfile.ZipFile(broken, "w") as output:
            for info, data in ordered:
                compress = mimetype_compress if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
                output.writestr(info.filename, data, compress_type=compress)
            if extra:
                output.writestr(extra, b"x")
        return broken

    def test_verify_rejects_changed_members_and_bad_mimetype(self):
        entry = self._entry("86 Vol.01.epub")
        plan = self._plan(entry.path)
        staged = self.root / "out.epub"
        self.adapter.build(entry, plan, staged)
        self.adapter.verify(staged, plan)
        cases = {
            "extra member": self._rebuild(staged, "extra", extra="OEBPS/extra.txt"),
            "deflated mimetype": self._rebuild(staged, "deflated", mimetype_compress=zipfile.ZIP_DEFLATED),
            "mimetype not first": self._rebuild(staged, "last", mimetype_last=True),
        }
        for name, broken in cases.items():
            with self.subTest(case=name), self.assertRaises(BuildError):
                self.adapter.verify(broken, plan)
            broken.unlink()

    def test_verify_rejects_wrong_metadata_and_truncated_file(self):
        entry = self._entry("86 Vol.01.epub")
        plan = self._plan(entry.path)
        staged = self.root / "out.epub"
        self.adapter.build(entry, plan, staged)
        for wrong in (replace(plan.metadata, series="别的"), replace(plan.metadata, series_index=Decimal(2)),
                      replace(plan.metadata, title="别的书名"), replace(plan.metadata, language="ja")):
            with self.subTest(wrong=wrong), self.assertRaises(BuildError):
                self.adapter.verify(staged, replace(plan, metadata=wrong))
        staged.write_bytes(staged.read_bytes()[:50])
        with self.assertRaises(BuildError):
            self.adapter.verify(staged, plan)

    def _corrupt_opf(self, path):
        """Re-store the OPF deflated, then damage its compressed stream (zlib.error on read)."""
        with zipfile.ZipFile(path) as archive:
            members = [(info.filename, archive.read(info)) for info in archive.infolist()]
        with zipfile.ZipFile(path, "w") as output:
            for name, data in members:
                compress = zipfile.ZIP_DEFLATED if name.endswith(".opf") else zipfile.ZIP_STORED
                output.writestr(name, data, compress_type=compress)
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("OEBPS/content.opf")
        data = bytearray(path.read_bytes())
        start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
        for offset in range(start + 2, start + 12):
            data[offset] ^= 0xFF
        path.write_bytes(bytes(data))
        return path

    def test_corrupt_opf_stream_has_no_facts_and_fails_to_build(self):
        entry = self._entry("86 Vol.01.epub")
        self._corrupt_opf(entry.path)
        self.assertEqual(self.adapter.facts(entry), {})
        staged = self.root / "out.epub"
        with self.assertRaises(BuildError):
            self.adapter.build(entry, self._plan(entry.path), staged)
        self.assertFalse(staged.exists())

    def test_verify_wraps_corrupt_output(self):
        entry = self._entry("86 Vol.01.epub")
        plan = self._plan(entry.path)
        staged = self.root / "out.epub"
        self.adapter.build(entry, plan, staged)
        self._corrupt_opf(staged)
        with self.assertRaises(BuildError):
            self.adapter.verify(staged, plan)

    def test_bad_opf_xml_build_fails(self):
        entry = self._entry("86 Vol.01.epub")
        with zipfile.ZipFile(entry.path) as archive:
            members = [(info.filename, archive.read(info)) for info in archive.infolist()]
        with zipfile.ZipFile(entry.path, "w") as output:
            for name, data in members:
                output.writestr(name, b"<package><unclosed" if name.endswith(".opf") else data)
        staged = self.root / "out.epub"
        with self.assertRaises(BuildError):
            self.adapter.build(entry, self._plan(entry.path), staged)
        self.assertFalse(staged.exists())

if __name__ == "__main__":
    unittest.main()
