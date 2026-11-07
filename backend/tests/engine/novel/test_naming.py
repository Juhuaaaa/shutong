"""Tests for light novel naming helpers."""
from decimal import Decimal
import re
import unicodedata
import unittest

from shutong.engine.kinds.novel import naming
from shutong.engine.kinds.novel.naming import (
    DEFAULT_VOLUME_PATTERN,
    NovelVolume,
    target_filename,
)


class NamingTests(unittest.TestCase):
    def test_ep_volume_pattern_ignores_specials(self) -> None:
        pattern = re.compile(r"(?i)(?<![A-Za-z0-9])Ep\.?\s*0*(\d+)(?![0-9])")
        self.assertEqual(
            1, naming.volume_from_name("86─不存在的战区─ Ep.01", pattern)
        )
        self.assertEqual(
            11,
            naming.volume_from_name(
                "86─不存在的战区─ EP.11 ─Dies passionis─", pattern
            ),
        )
        self.assertIsNone(
            naming.volume_from_name(
                "86─不存在的战区─ Alter.1 ─死神偶尔挥洒青春─", pattern
            )
        )

    def test_overlord_volume_pattern_ignores_specials(self) -> None:
        pattern = re.compile(r"(?i)^OVERLORD\s+0*(\d+)(?=\s|$)")
        self.assertEqual(1, naming.volume_from_name("OVERLORD 1", pattern))
        self.assertEqual(
            10, naming.volume_from_name("OVERLORD 10 谋略的统治者", pattern)
        )
        self.assertIsNone(naming.volume_from_name("OVERLORD(WEB版)", pattern))
        self.assertIsNone(
            naming.volume_from_name("OVERLORD × 霸劍皇姬阿爾緹娜短篇", pattern)
        )
        self.assertIsNone(
            naming.volume_from_name("[丸山くがね].OVERLORD BD特典（网翻）", pattern)
        )
        self.assertIsNone(naming.volume_from_name("00 Prologue", pattern))

    def test_filenames(self) -> None:
        self.assertEqual(
            "OVERLORD Vol.01.epub", naming.volume_filename("OVERLORD", 1, 2)
        )
        self.assertEqual(
            "OVERLORD Vol.16.epub", naming.volume_filename("OVERLORD", 16, 2)
        )
        self.assertEqual(
            "OVERLORD SP01.epub", naming.special_filename("OVERLORD", 1)
        )
        self.assertEqual(
            "OVERLORD SP10.epub", naming.special_filename("OVERLORD", 10)
        )

    def test_natural_key_orders_numbers(self) -> None:
        values = ["第10卷", "第2卷", "第1卷"]
        self.assertEqual(
            ["第1卷", "第2卷", "第10卷"],
            sorted(values, key=naming.natural_key),
        )

    def test_natural_key_handles_mixed_prefixes(self) -> None:
        values = ["短篇+特典/00 序篇", "00 Prologue", "OVERLORD(WEB版)"]
        self.assertEqual(
            ["00 Prologue", "OVERLORD(WEB版)", "短篇+特典/00 序篇"],
            sorted(values, key=naming.natural_key),
        )

    def test_special_filename_detection(self) -> None:
        self.assertTrue(naming.is_special_filename("系列 SP01.epub"))
        self.assertTrue(naming.is_special_filename("系列 sp12.epub"))
        self.assertFalse(naming.is_special_filename("系列 Vol.01.epub"))

    def test_decimal_and_zero_volumes(self) -> None:
        pattern = re.compile(r"(?i)^Title\s+0*(\d+(?:\.\d+)?)")
        self.assertEqual(
            Decimal("7.5"), naming.volume_from_name("Title 07.5", pattern)
        )
        self.assertEqual(Decimal("0"), naming.volume_from_name("Title 00", pattern))
        self.assertEqual(
            "Series Vol.07.5.epub",
            naming.volume_filename("Series", Decimal("7.5"), 2),
        )
        self.assertEqual(
            "Series Vol.00.epub",
            naming.volume_filename("Series", Decimal("0"), 2),
        )
        self.assertEqual(
            "Series Vol.12.5.epub",
            naming.volume_filename("Series", Decimal("12.5"), 2),
        )

    def test_roman_numerals(self) -> None:
        pattern = re.compile(r"^狼与辛香料\s+([IVXLCDM]+)(?![A-Za-z])")
        self.assertEqual(
            Decimal(11),
            naming.volume_from_name(
                unicodedata.normalize("NFKC", "狼与辛香料 Ⅺ Side ColorsⅡ"),
                pattern,
            ),
        )
        self.assertEqual(24, naming.roman_to_int("XXIV"))
        self.assertEqual(19, naming.roman_to_int("ⅩⅨ"))
        self.assertIsNone(naming.roman_to_int("ABC"))

    def test_alternation_capture_groups(self) -> None:
        pattern = re.compile(r"\[(\d{1,2})\]|^加速世界\s+(\d{1,2})(?=\s|$)")
        self.assertEqual(
            Decimal(3), naming.volume_from_name("[川原砾][加速世界][03][暮色]", pattern)
        )
        self.assertEqual(
            Decimal(27),
            naming.volume_from_name("加速世界 27 第四个加速", pattern),
        )

    def test_pattern_captures_declared_zero_padding(self) -> None:
        pattern = re.compile(r"(?i)(?<![A-Za-z0-9])Ep\.?\s*0*(\d+)(?![0-9])")
        self.assertEqual(3, naming.volume_from_name("Ep.03", pattern))

    def test_volume_zero_and_decimal(self) -> None:
        pattern = re.compile(DEFAULT_VOLUME_PATTERN)
        self.assertEqual(naming.volume_from_name("86 Vol.0", pattern), Decimal(0))
        self.assertEqual(naming.volume_from_name("86 Vol.7.5", pattern), Decimal("7.5"))
        self.assertEqual(target_filename("86", NovelVolume.volume(Decimal(0))), "86 Vol.00.epub")
        self.assertEqual(target_filename("86", NovelVolume.volume(Decimal("7.5"))), "86 Vol.07.5.epub")

    def test_special_needs_index(self) -> None:
        self.assertEqual(target_filename("86", NovelVolume.special(), special_index=1), "86 SP01.epub")
        with self.assertRaises(ValueError):
            target_filename("86", NovelVolume.special())

    def test_volume_keys(self) -> None:
        self.assertEqual(NovelVolume.volume(Decimal("1.0")).key(), "volume:1")
        self.assertEqual(NovelVolume.volume(Decimal("7.50")).key(), "volume:7.5")
        self.assertEqual(NovelVolume.special().key(), "special")

if __name__ == "__main__":
    unittest.main()
