from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree
import zipfile

from shutong.engine.kinds.manga.comicinfo import ComicMetadata, build_comic_info, read_comic_info
from shutong.engine.kinds.manga.volume import VolumeRef


def make_metadata(**overrides):
    values = {
        "series_name": "间谍过家家[bili电子版]",
        "subject_id": 279379,
        "localized_series": "间谍过家家",
        "volume": VolumeRef.volume(Decimal("19")),
        "title": "Vol.19",
        "summary": "summary",
        "writers": ("远藤达哉",),
        "publisher": "集英社",
        "release_date": "2019-03-25",
        "genres": ("漫画", "喜剧"),
        "language": "zh",
        "manga_direction": "YesAndRightToLeft",
        "completed": False,
        "total_volumes": None,
    }
    values.update(overrides)
    return ComicMetadata(**values)


def render(metadata, page_count=210):
    return build_comic_info(metadata, page_count)


class ComicInfoTests(unittest.TestCase):
    def test_volume_metadata_keeps_editions_separate(self):
        metadata = make_metadata()
        root = ElementTree.fromstring(render(metadata))
        self.assertEqual(root.findtext("Series"), "间谍过家家[bili电子版]")
        self.assertEqual(root.findtext("LocalizedSeries"), "间谍过家家")
        self.assertEqual(root.findtext("SeriesSort"), "间谍过家家[bili电子版]")
        self.assertEqual(root.findtext("Volume"), "19")
        self.assertIsNone(root.find("Number"))
        self.assertIsNone(root.find("Count"))
        self.assertEqual(root.findtext("PageCount"), "210")
        self.assertEqual(root.findtext("Web"), "https://bgm.tv/subject/279379")
        self.assertEqual(root.findtext("Year"), "2019")
        self.assertEqual(root.findtext("Month"), "3")
        self.assertEqual(root.findtext("Day"), "25")

    def test_completed_series_writes_reliable_count(self):
        complete = make_metadata(completed=True, total_volumes=12)
        complete_root = ElementTree.fromstring(render(complete))
        self.assertEqual(complete_root.findtext("Count"), "12")

        unknown_count = make_metadata(completed=True, total_volumes=None)
        unknown_root = ElementTree.fromstring(render(unknown_count))
        self.assertIsNone(unknown_root.find("Count"))

    def test_special_volume_uses_kavita_special_fields(self):
        root = ElementTree.fromstring(
            render(make_metadata(volume=VolumeRef.special(1, "番外")))
        )

        self.assertIsNone(root.find("Volume"))
        self.assertEqual(root.findtext("Number"), "SP01")
        self.assertEqual(root.findtext("Format"), "Special")

    def test_chapter_is_a_number_without_volume(self):
        root = ElementTree.fromstring(render(make_metadata(volume=VolumeRef.chapter(Decimal("15")), title="Ch.0015")))
        self.assertIsNone(root.find("Volume"))
        self.assertEqual((root.findtext("Number"), root.findtext("Title")), ("15", "Ch.0015"))

    def test_chapter_range_is_a_number_range(self):
        root = ElementTree.fromstring(render(make_metadata(volume=VolumeRef.chapter(Decimal("1"), Decimal("40")))))
        self.assertIsNone(root.find("Volume"))
        self.assertEqual(root.findtext("Number"), "1-40")

    def test_range_volume_uses_normalized_inclusive_range(self):
        root = ElementTree.fromstring(
            render(
                make_metadata(volume=VolumeRef.range(Decimal("7.5"), Decimal("8")))
            )
        )

        self.assertEqual(root.findtext("Volume"), "7.5-8")
        self.assertIsNone(root.find("Number"))

    def test_volume_keeps_significant_trailing_zero(self):
        # Regression: "10" must not be stripped to "1" like a fraction tail.
        for raw, expected in (
            ("10", "10"),
            ("20", "20"),
            ("90", "90"),
            ("100", "100"),
            ("110", "110"),
            ("19.50", "19.5"),
            ("19", "19"),
        ):
            with self.subTest(raw=raw):
                root = ElementTree.fromstring(
                    render(
                        make_metadata(volume=VolumeRef.volume(Decimal(raw)))
                    )
                )
                self.assertEqual(root.findtext("Volume"), expected)

    def test_range_volume_keeps_significant_trailing_zeros(self):
        root = ElementTree.fromstring(
            render(
                make_metadata(
                    volume=VolumeRef.range(Decimal("10"), Decimal("20.50"))
                )
            )
        )

        self.assertEqual(root.findtext("Volume"), "10-20.5")

    def test_metadata_omits_malformed_optional_values(self):
        root = ElementTree.fromstring(
            render(
                make_metadata(
                    release_date="2019-3-05",
                    writers=("远藤达哉", "", "远藤达哉", "古桥秀之"),
                    genres=("漫画", "", "漫画", "喜剧"),
                    completed=True,
                    total_volumes=True,
                    series_name="间谍过家家",
                    subject_id=True,
                ),
                page_count=-1,
            )
        )

        self.assertIsNone(root.find("Year"))
        self.assertIsNone(root.find("Month"))
        self.assertIsNone(root.find("Day"))
        self.assertEqual(root.findtext("Writer"), "远藤达哉, 古桥秀之")
        self.assertEqual(root.findtext("Genre"), "漫画, 喜剧")
        self.assertEqual(root.findtext("Tags"), "漫画, 喜剧")
        self.assertIsNone(root.find("PageCount"))
        self.assertIsNone(root.find("Count"))
        self.assertIsNone(root.find("Web"))

    def test_output_escapes_text_and_has_no_doctype(self):
        content = render(
            make_metadata(title="A < B & C\x01", summary="A < B & C\x01")
        )
        root = ElementTree.fromstring(content)

        self.assertEqual(root.findtext("Title"), "A < B & C")
        self.assertEqual(root.findtext("Summary"), "A < B & C")
        self.assertNotIn(b"<!DOCTYPE", content)

    def test_output_removes_surrogates_and_noncharacters(self):
        unsafe = "ok\ud800\ufdd0\ufffe\uffff\U0001fffe\U0001ffff"
        content = render(make_metadata(title=unsafe, summary=unsafe))
        root = ElementTree.fromstring(content)

        self.assertEqual(root.findtext("Title"), "ok")
        self.assertEqual(root.findtext("Summary"), "ok")
        for code_point in (0xD800, 0xFDD0, 0xFFFE, 0xFFFF, 0x1FFFE, 0x1FFFF):
            self.assertNotIn(chr(code_point).encode("utf-8", "surrogatepass"), content)

    def test_volume_zero_is_a_real_volume(self):
        # Many series have a Vol.0 (旋风管家, 实力至上主义的教室); Kavita marks "no volume" with
        # -100000, not 0, so writing 0 keeps it a volume of its own.
        root = ElementTree.fromstring(render(make_metadata(volume=VolumeRef.volume(Decimal("0")))))
        self.assertEqual(root.findtext("Volume"), "0")
        root = ElementTree.fromstring(render(make_metadata(volume=VolumeRef.range(Decimal("0"), Decimal("1")))))
        self.assertEqual(root.findtext("Volume"), "0-1")

    def test_invalid_volume_references_raise_value_error(self):
        cases = (
            ("ordinary NaN", VolumeRef.volume(Decimal("NaN"))),
            ("ordinary infinity", VolumeRef.volume(Decimal("Infinity"))),
            ("ordinary negative", VolumeRef.volume(Decimal("-1"))),
            ("range NaN start", VolumeRef.range(Decimal("NaN"), Decimal("1"))),
            ("range infinity end", VolumeRef.range(Decimal("1"), Decimal("Infinity"))),
            ("range negative start", VolumeRef.range(Decimal("-1"), Decimal("1"))),
            ("reversed range", VolumeRef.range(Decimal("2"), Decimal("1"))),
            ("missing ordinary bound", VolumeRef(kind="volume")),
            ("unknown kind", VolumeRef(kind="other", start=Decimal("1"))),
            ("nonpositive special", VolumeRef.special(0)),
        )

        for description, volume in cases:
            with self.subTest(description=description):
                with self.assertRaisesRegex(ValueError, "invalid volume"):
                    render(make_metadata(volume=volume))

    def test_read_comic_info_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            cbz = Path(directory) / "a.cbz"
            with zipfile.ZipFile(cbz, "w") as archive:
                archive.writestr("001.jpg", b"x")
                archive.writestr("ComicInfo.xml", render(make_metadata()))
            fields = read_comic_info(cbz)
        self.assertEqual(fields["Series"], "间谍过家家[bili电子版]")
        self.assertEqual(fields["Volume"], "19")
        self.assertEqual(fields["PageCount"], "210")


if __name__ == "__main__":
    unittest.main()
