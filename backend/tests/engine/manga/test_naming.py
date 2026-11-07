from decimal import Decimal
import unittest

from shutong.engine.kinds.manga.naming import (
    build_archive_name,
    build_output_name,
    normalize_title,
    parse_chapter,
    parse_volume,
)
from shutong.engine.kinds.manga.volume import VolumeRef


class NamingTests(unittest.TestCase):
    def test_normalizes_traditional_title_but_preserves_english(self):
        self.assertEqual(normalize_title("魔女與使魔"), "魔女与使魔")
        self.assertEqual(normalize_title("To LOVEる"), "To LOVEる")

    def test_parses_volume_forms(self):
        self.assertEqual(parse_volume("Volume 1.zip").key(), "volume:1")
        self.assertEqual(parse_volume("第19卷.zip").key(), "volume:19")
        self.assertEqual(parse_volume("Vol.19.5.zip").key(), "volume:19.5")
        self.assertEqual(parse_volume("Vol.20-21.zip").key(), "range:20-21")
        self.assertEqual(parse_volume("SP01 番外.zip").key(), "special:1")

    def test_parses_supported_volume_markers_with_decimal_values(self):
        self.assertEqual(parse_volume("v 7.5.zip").start, Decimal("7.5"))
        self.assertEqual(parse_volume("19巻.zip").key(), "volume:19")

    def test_does_not_invent_volume_from_sort_order(self):
        self.assertIsNone(parse_volume("新下载.zip"))

    def test_builds_kavita_safe_names(self):
        output = build_output_name("间谍过家家", "bili电子版")
        volume = parse_volume("Vol.19.zip")
        self.assertEqual(output, "间谍过家家[bili电子版]")
        self.assertEqual(
            build_archive_name(output, volume, width=2),
            "间谍过家家[bili电子版] Vol.19.cbz",
        )

    def test_builds_editionless_name_only_when_no_edition_is_given(self):
        self.assertEqual(build_output_name("间谍过家家", None), "间谍过家家")
        # Characters Windows and SMB shares refuse in names become their full-width forms.
        self.assertEqual(build_output_name("Re:从零开始的异世界生活", "台版?"), "Re：从零开始的异世界生活[台版？]")
        self.assertEqual(build_output_name('A*B<C>D|E"F', None), "A＊B＜C＞D｜E＂F")

    def test_fullwidth_volume_digits(self):
        self.assertEqual(parse_volume("间谍过家家 Vol.０１.zip"), VolumeRef.volume(Decimal(1)))

    def test_chinese_numeral_volume_is_not_guessed(self):
        self.assertIsNone(parse_volume("间谍过家家 第一卷.zip"))
        self.assertIsNone(parse_volume("间谍过家家.zip"))

    def test_range_and_special(self):
        self.assertEqual(parse_volume("x 第01-05卷.rar").key(), "range:1-5")
        self.assertEqual(parse_volume("x SP02.zip").key(), "special:2")


DAWANG = "[大王饶命][阅动文化 x 小鱼的蝴蝶结][Chap.001-Chap.866]"
TOWER = "[SIU][神之塔][未完][webtoons][电子版]"


class ChapterTests(unittest.TestCase):
    def test_parse_chapter_spellings(self):
        for name, number in (("某漫画 第15话.zip", "15"), ("某漫画 第15話.zip", "15"), ("X Chap.15.zip", "15"),
                             ("X Chapter 15.cbz", "15"), ("X Ch.15.zip", "15"), ("X #15.zip", "15"),
                             ("X 15.5话.zip", "15.5"), ("X ch015.zip", "15")):
            with self.subTest(name=name):
                self.assertEqual(parse_chapter(name), VolumeRef.chapter(Decimal(number)))
        for name in ("Church 3.zip", "X Vol.15.zip", "X 第2季.zip", "X 15.zip"):
            with self.subTest(name=name):
                self.assertIsNone(parse_chapter(name))

    def test_chapter_ranges_are_not_single_chapters(self):
        for name in ("某漫画 第1-10话.zip", "[某漫画][第1-120话]", "某漫画 Ch.1-5.zip", "X Chap.001-Chap.010.zip"):
            with self.subTest(name=name):
                self.assertIsNone(parse_chapter(name))

if __name__ == "__main__":
    unittest.main()
