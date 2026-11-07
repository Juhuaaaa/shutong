from decimal import Decimal
import unittest

from shutong.engine.kinds.manga.volume import VolumeRef
from shutong.engine.kinds.novel.naming import NovelVolume
from shutong.engine.metadata_build import (
    manga_metadata, metadata_from_json, metadata_to_json, novel_metadata, volume_from_key,
)
from shutong.engine.recognition import Directives
from shutong.metadata.base import Subject

SUBJECT = Subject(subject_id=279379, name="SPY×FAMILY", name_cn="间谍过家家", summary="  一家人\n的故事  ",
                  release_date="2019-03-25", writers=("远藤达哉",), publisher="集英社",
                  genres=("漫画", "喜剧", "2019", "远藤达哉", "日本", "间谍过家家", "家庭"),
                  completed=True, total_volumes=12, platform="漫画")


class MetadataBuildTests(unittest.TestCase):

    def test_manga_directives_override_language_and_direction(self):
        meta = manga_metadata("x", VolumeRef.volume(Decimal(1)), SUBJECT, Directives(lang="ja", direction="No"), 3)
        self.assertEqual((meta.language, meta.manga_direction, meta.title), ("ja", "No", "Vol.001"))

    def test_novel_first_volume_only_has_description(self):
        first = novel_metadata("间谍过家家", NovelVolume.volume(Decimal(1)), SUBJECT, {"title": "第一卷"},
                               Directives(), first_volume=True, fallback_title="stem")
        later = novel_metadata("间谍过家家", NovelVolume.volume(Decimal(2)), SUBJECT, {"title": "第二卷"},
                               Directives(), first_volume=False, fallback_title="stem")
        self.assertEqual((first.description, later.description), ("一家人 的故事", ""))
        self.assertEqual((first.series_index, first.title, first.web_url), (Decimal(1), "第一卷",
                                                                          "https://bgm.tv/subject/279379"))
        self.assertEqual((first.authors, first.publisher, first.date, first.language),
                         (("远藤达哉",), "集英社", "2019-03-25", "zh"))

    def test_novel_special_index_and_title_fallback(self):
        meta = novel_metadata("x", NovelVolume.special(), SUBJECT, {"title": "  "}, Directives(lang="ja"),
                              first_volume=False, fallback_title="86 番外篇")
        self.assertEqual((meta.series_index, meta.title, meta.language), (Decimal(100000), "86 番外篇", "ja"))
        self.assertEqual(novel_metadata("x", NovelVolume.special(), SUBJECT, {}, Directives(),
                                        first_volume=False, fallback_title="stem").title, "stem")

    def test_json_round_trip(self):
        for volume in (VolumeRef.volume(Decimal("7.5")), VolumeRef.range(Decimal(1), Decimal(5)), VolumeRef.special(2)):
            with self.subTest(manga=volume.key()):
                meta = manga_metadata("x", volume, SUBJECT, Directives(), 2)
                self.assertEqual(metadata_from_json("manga", metadata_to_json(meta)), meta)
        for volume in (NovelVolume.volume(Decimal(0)), NovelVolume.special()):
            with self.subTest(novel=volume.key()):
                meta = novel_metadata("x", volume, SUBJECT, {"title": "t"}, Directives(),
                                      first_volume=True, fallback_title="f")
                self.assertEqual(metadata_from_json("novel", metadata_to_json(meta)), meta)

    def test_volume_from_key(self):
        self.assertEqual(volume_from_key("manga", "range:1-5"), VolumeRef.range(Decimal(1), Decimal(5)))
        self.assertEqual(volume_from_key("manga", "special:2"), VolumeRef.special(2))
        self.assertEqual(volume_from_key("manga", "chapter:1-40"), VolumeRef.chapter(Decimal(1), Decimal(40)))
        self.assertEqual(volume_from_key("novel", "special"), NovelVolume.special())
        self.assertEqual(volume_from_key("novel", "volume:7.5"), NovelVolume.volume(Decimal("7.5")))


if __name__ == "__main__":
    unittest.main()
