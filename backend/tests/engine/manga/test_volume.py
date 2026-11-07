from decimal import Decimal
import unittest

from shutong.engine.kinds.manga.volume import VolumeRef


class VolumeRefTests(unittest.TestCase):
    def test_volume_ref_formats_volume_decimal_range_and_special(self):
        self.assertEqual(VolumeRef.volume(Decimal("19")).token(2), "Vol.19")
        self.assertEqual(VolumeRef.volume(Decimal("7.5")).token(2), "Vol.07.5")
        self.assertEqual(
            VolumeRef.range(Decimal("20"), Decimal("21")).token(2),
            "Vol.20-21",
        )
        self.assertEqual(VolumeRef.special(1, "番外").token(2), "SP01 番外")

    def test_volume_ref_keys_canonicalize_fixed_point_decimals(self):
        self.assertEqual(VolumeRef.volume(Decimal("1")).key(), "volume:1")
        self.assertEqual(VolumeRef.volume(Decimal("1.0")).key(), "volume:1")
        self.assertEqual(VolumeRef.volume(Decimal("1.00")).key(), "volume:1")
        self.assertEqual(VolumeRef.volume(Decimal("7.50")).key(), "volume:7.5")
        self.assertEqual(
            VolumeRef.range(Decimal("3.00"), Decimal("4.50")).key(),
            "range:3-4.5",
        )


    def test_chapter_range_keeps_both_ends(self):
        # 仙王的日常生活 ships 40 chapters per archive: Ch.0001-0040, not Ch.0001.
        chapters = VolumeRef.chapter(Decimal("1"), Decimal("40"))
        self.assertEqual((chapters.kind, chapters.key(), chapters.token(4)),
                         ("chapter", "chapter:1-40", "Ch.0001-0040"))
        self.assertEqual(VolumeRef.chapter(Decimal("3"), Decimal("3")), VolumeRef.chapter(Decimal("3")))

    def test_chapter_key_and_token(self):
        chapter = VolumeRef.chapter(Decimal("15"))
        self.assertEqual((chapter.kind, chapter.key(), chapter.token(4)), ("chapter", "chapter:15", "Ch.0015"))
        self.assertEqual(VolumeRef.chapter(Decimal("15.50")).token(4), "Ch.0015.5")

if __name__ == "__main__":
    unittest.main()
