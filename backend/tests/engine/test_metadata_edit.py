from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
import zipfile

from shutong.engine.kinds.manga.comicinfo import ComicMetadata, build_comic_info, read_comic_info
from shutong.engine.kinds.manga.volume import VolumeRef
from shutong.engine.kinds.novel.epub import KavitaMetadata
from shutong.engine.metadata_edit import ManualMetadata, apply_manual, apply_subject, rewrite_cbz
from shutong.metadata.base import Subject


def manga(**changes):
    values = dict(series_name="仙王的日常生活", volume=VolumeRef.chapter(Decimal(1), Decimal(40)), title="Ch.0001-0040",
                  language="zh", manga_direction="YesAndRightToLeft")
    values.update(changes)
    return ComicMetadata(**values)


def novel(**changes):
    values = dict(series="败北女角太多了！", series_index=Decimal(1), title="败北女角太多了！ 1", language="zh")
    values.update(changes)
    return KavitaMetadata(**values)


SUBJECT = Subject(subject_id=302561, name="나 혼자만 레벨업", name_cn="我独自升级", summary="猎人的故事",
                  release_date="2018-03-04", writers=("추공",), publisher="D&C", genres=("奇幻", "2018"),
                  completed=True, total_volumes=14, platform="漫画")


class ManualMetadataTests(unittest.TestCase):
    def test_reads_and_cleans_what_a_person_typed(self):
        manual = ManualMetadata.from_json({"writers": [" 雾月凌 ", "", "雾月凌"], "genres": ["修仙", "搞笑"],
                                           "summary": "  王令的日常  ", "release_date": "2016",
                                           "publisher": "", "localized_series": "仙王的日常生活"})
        self.assertEqual(manual.writers, ("雾月凌",))
        self.assertEqual(manual.summary, "王令的日常")
        self.assertEqual(manual.release_date, "2016")
        self.assertEqual(ManualMetadata.from_json(manual.to_json()), manual)

    def test_rejects_dates_that_are_not_dates(self):
        for value in ("2016-13", "16年", "2016-02-30"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "发售日期"):
                ManualMetadata.from_json({"release_date": value})

    def test_nothing_filled_in_is_refused(self):
        with self.assertRaisesRegex(ValueError, "至少填一项"):
            ManualMetadata.from_json({"writers": [" "], "summary": ""})


class ApplyTests(unittest.TestCase):
    def test_manual_fields_replace_the_text_but_keep_the_file_identity(self):
        manual = ManualMetadata.from_json({"writers": ["雾月凌"], "summary": "王令的日常", "genres": ["修仙"],
                                           "release_date": "2016-08", "localized_series": "仙王的日常生活"})
        edited = apply_manual(manga(subject_id=None), manual)
        self.assertEqual((edited.series_name, edited.volume.key(), edited.title),
                         ("仙王的日常生活", "chapter:1-40", "Ch.0001-0040"))
        self.assertEqual((edited.writers, edited.summary, edited.genres, edited.release_date),
                         (("雾月凌",), "王令的日常", ("修仙",), "2016-08"))
        self.assertIsNone(edited.subject_id)

    def test_illustrators_typed_for_a_novel_are_written(self):
        manual = ManualMetadata.from_json({"illustrators": [" ももこ ", "ももこ"]})
        self.assertEqual(manual.illustrators, ("ももこ",))
        self.assertEqual(ManualMetadata.from_json(manual.to_json()), manual)
        self.assertEqual(apply_manual(novel(illustrators=("旧",)), manual).illustrators, ("ももこ",))
        self.assertEqual(apply_manual(manga(), manual).writers, ())  # comics have no such field

    def test_a_subject_brings_the_illustrators_to_a_novel(self):
        book = apply_subject(novel(), replace(SUBJECT, illustrators=("ももこ",)))
        self.assertEqual(book.illustrators, ("ももこ",))

    def test_manual_fields_on_a_novel(self):
        manual = ManualMetadata.from_json({"writers": ["雨森たきび"], "summary": "败犬的故事", "release_date": "2021"})
        edited = apply_manual(novel(), manual)
        self.assertEqual((edited.authors, edited.description, edited.date, edited.series),
                         (("雨森たきび",), "败犬的故事", "2021", "败北女角太多了！"))

    def test_a_subject_replaces_everything_it_knows(self):
        edited = apply_subject(manga(summary="旧", writers=("旧",)), SUBJECT)
        self.assertEqual((edited.subject_id, edited.localized_series, edited.summary, edited.writers),
                         (302561, "我独自升级", "猎人的故事", ("추공",)))
        self.assertEqual((edited.completed, edited.total_volumes, edited.series_name), (True, 14, "仙王的日常生活"))
        book = apply_subject(novel(), SUBJECT)
        self.assertEqual((book.web_url, book.authors, book.genres, book.date),
                         ("https://bgm.tv/subject/302561", ("추공",), ("奇幻",), "2018-03-04"))


class ComicInfoDateTests(unittest.TestCase):
    def test_partial_dates_write_what_is_known(self):
        def fields(date):
            root = build_comic_info(manga(release_date=date), 1).decode()
            return [tag for tag in ("<Year>", "<Month>", "<Day>") if tag in root]
        self.assertEqual(fields("2016"), ["<Year>"])
        self.assertEqual(fields("2016-08"), ["<Year>", "<Month>"])
        self.assertEqual(fields("2016-08-01"), ["<Year>", "<Month>", "<Day>"])


class RewriteCbzTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.cbz = self.dir / "Ch.0001-0040.cbz"
        with zipfile.ZipFile(self.cbz, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for number in range(1, 4):
                archive.writestr("{0:03d}.jpg".format(number), b"\xff\xd8\xff" + bytes([number]) * 100)
            archive.writestr("ComicInfo.xml", build_comic_info(manga(), 3))

    def test_only_comic_info_changes(self):
        before = self.pages()
        rewrite_cbz(self.cbz, apply_manual(manga(), ManualMetadata.from_json({"summary": "王令的日常"})))
        self.assertEqual(self.pages(), before)
        info = read_comic_info(self.cbz)
        self.assertEqual((info["Summary"], info["PageCount"], info["Series"]), ("王令的日常", "3", "仙王的日常生活"))
        self.assertEqual(sorted(path.name for path in self.dir.iterdir()), ["Ch.0001-0040.cbz"])

    def test_a_broken_archive_is_left_as_it_was(self):
        self.cbz.write_bytes(b"not a zip")
        with self.assertRaises(zipfile.BadZipFile):
            rewrite_cbz(self.cbz, manga())
        self.assertEqual(self.cbz.read_bytes(), b"not a zip")
        self.assertEqual(sorted(path.name for path in self.dir.iterdir()), ["Ch.0001-0040.cbz"])

    def pages(self):
        with zipfile.ZipFile(self.cbz) as archive:
            return [(name, archive.read(name)) for name in archive.namelist() if name != "ComicInfo.xml"]


if __name__ == "__main__":
    unittest.main()
