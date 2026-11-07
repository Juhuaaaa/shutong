from decimal import Decimal
import unittest

from shutong.engine.kinds.manga.volume import VolumeRef
from shutong.engine.kinds.novel.naming import NovelVolume
from shutong.engine.overrides import parse_volume_for, parse_volume_text


class ParseVolumeTextTests(unittest.TestCase):
    def test_accepted_forms(self):
        for text, expected in [
            ("13", VolumeRef.volume(Decimal("13"))),
            ("1.5", VolumeRef.volume(Decimal("1.5"))),
            ("1-5", VolumeRef.range(Decimal("1"), Decimal("5"))),
            ("01-05", VolumeRef.range(Decimal("1"), Decimal("5"))),
            ("SP1", VolumeRef.special(1)),
            (" sp01 ", VolumeRef.special(1)),
            ("Ch.15", VolumeRef.chapter(Decimal("15"))),
            ("第15话", VolumeRef.chapter(Decimal("15"))),
            ("15話", VolumeRef.chapter(Decimal("15"))),
            ("Ch.1-40", VolumeRef.chapter(Decimal("1"), Decimal("40"))),
            ("第1-40话", VolumeRef.chapter(Decimal("1"), Decimal("40"))),
        ]:
            with self.subTest(text=text):
                self.assertEqual(parse_volume_text(text).key(), expected.key())

    def test_rejects_other_text(self):
        with self.assertRaisesRegex(ValueError, "无法识别的卷号"):
            parse_volume_text("第一卷")

    def test_a_novel_gets_a_novel_volume(self):
        self.assertEqual(parse_volume_for("novel", "2"), NovelVolume.volume(Decimal("2")))
        self.assertEqual(parse_volume_for("novel", "12.5"), NovelVolume.volume(Decimal("12.5")))
        self.assertEqual(parse_volume_for("novel", "SP3"), NovelVolume.special())
        self.assertEqual(parse_volume_for("manga", "2").key(), VolumeRef.volume(Decimal("2")).key())

    def test_a_novel_has_no_ranges_or_chapters(self):
        for text in ("1-5", "Ch.15", "第15话"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "轻小说"):
                parse_volume_for("novel", text)


if __name__ == "__main__":
    unittest.main()
