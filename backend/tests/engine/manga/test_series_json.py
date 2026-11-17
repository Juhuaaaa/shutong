from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from shutong.engine.kinds.manga.comicinfo import ComicMetadata, build_comic_info
from shutong.engine.kinds.manga.series_json import SERIES_JSON, write_series_json
from shutong.engine.kinds.manga.volume import VolumeRef


def cbz(path: Path, metadata=None, mtime=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("001.jpg", b"x")
        if metadata is not None:
            archive.writestr("ComicInfo.xml", build_comic_info(metadata, 1))
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def info(volume=1, **fields):
    values = dict(series_name="海贼王[Bilibili]", volume=VolumeRef.volume(Decimal(volume)), subject_id=975,
                  summary="草帽一伙的冒险。", publisher="集英社", release_date="1997-12-24")
    values.update(fields)
    return ComicMetadata(**values)


class SeriesJsonTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name) / "海贼王[Bilibili]"

    def written(self):
        return json.loads((self.folder / SERIES_JSON).read_text(encoding="utf-8"))["metadata"]

    def test_komga_reads_the_series_name_without_a_volume_suffix(self):
        cbz(self.folder / "Vol.04.cbz", info(4))
        self.assertTrue(write_series_json(self.folder))
        metadata = self.written()
        self.assertEqual(metadata["name"], "海贼王[Bilibili]")
        self.assertEqual(metadata["volume"], 1)  # anything else and Komga appends " (year)"

    def test_series_details_come_from_comic_info(self):
        cbz(self.folder / "Vol.01.cbz", info())
        write_series_json(self.folder)
        metadata = self.written()
        self.assertEqual((metadata["description_text"], metadata["publisher"], metadata["year"]),
                         ("草帽一伙的冒险。", "集英社", 1997))
        self.assertEqual(metadata["status"], "Continuing")

    def test_a_finished_series_is_ended_with_its_volume_count(self):
        cbz(self.folder / "Vol.01.cbz", info(completed=True, total_volumes=12))
        write_series_json(self.folder)
        self.assertEqual((self.written()["status"], self.written()["total_issues"]), ("Ended", 12))

    def test_an_ongoing_series_counts_the_files_it_has(self):
        cbz(self.folder / "Vol.01.cbz", info(1))
        cbz(self.folder / "Vol.02.cbz", info(2))
        write_series_json(self.folder)
        self.assertEqual(self.written()["total_issues"], 2)

    def test_every_field_komga_requires_is_present(self):
        cbz(self.folder / "Vol.01.cbz", info(publisher="", release_date=None, summary=""))
        write_series_json(self.folder)
        metadata = self.written()
        for key, kind in (("type", str), ("publisher", str), ("name", str), ("comicid", str), ("year", int),
                          ("booktype", str), ("comic_image", str), ("total_issues", int),
                          ("publication_run", str), ("status", str)):
            self.assertIsInstance(metadata[key], kind, key)

    def test_the_newest_file_speaks_for_the_series(self):
        cbz(self.folder / "Vol.01.cbz", info(1, summary="旧简介"), mtime=1_000_000)
        cbz(self.folder / "Vol.02.cbz", info(2, summary="新简介"), mtime=2_000_000)
        write_series_json(self.folder)
        self.assertEqual(self.written()["description_text"], "新简介")

    def test_a_file_without_comic_info_falls_back_to_the_folder_name(self):
        cbz(self.folder / "Vol.01.cbz")
        write_series_json(self.folder)
        self.assertEqual(self.written()["name"], "海贼王[Bilibili]")

    def test_unchanged_content_is_not_rewritten(self):
        cbz(self.folder / "Vol.01.cbz", info())
        self.assertTrue(write_series_json(self.folder))
        self.assertFalse(write_series_json(self.folder))

    def test_a_folder_without_books_loses_its_series_json(self):
        self.folder.mkdir(parents=True)
        (self.folder / SERIES_JSON).write_text("{}", encoding="utf-8")
        self.assertFalse(write_series_json(self.folder))
        self.assertFalse((self.folder / SERIES_JSON).exists())

    def test_a_missing_folder_is_left_alone(self):
        self.assertFalse(write_series_json(self.folder))
        self.assertFalse(self.folder.exists())


if __name__ == "__main__":
    unittest.main()
