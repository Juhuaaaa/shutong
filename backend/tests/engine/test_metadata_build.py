from decimal import Decimal
import unittest

from shutong.engine.kinds.manga.volume import VolumeRef
from shutong.engine.kinds.novel.naming import NovelVolume
from dataclasses import replace

from shutong.engine.kinds.manga.comicinfo import build_comic_info
from shutong.engine.metadata_build import (
    bangumi_id, manga_metadata, metadata_from_json, metadata_to_json, novel_metadata, volume_from_key,
)
from shutong.engine.recognition import Directives
from shutong.metadata.base import Subject

SUBJECT = Subject(subject_id=279379, name="SPY×FAMILY", name_cn="间谍过家家", summary="  一家人\n的故事  ",
                  release_date="2019-03-25", writers=("远藤达哉",), publisher="集英社",
                  genres=("漫画", "喜剧", "2019", "远藤达哉", "日本", "间谍过家家", "家庭"),
                  completed=True, total_volumes=12, platform="漫画")


ANILIST = replace(SUBJECT, subject_id="30002", source="anilist", name_cn="", aliases=("Spy x Family",))


class MetadataBuildTests(unittest.TestCase):

    def test_anilist_web_link_in_comicinfo(self):
        meta = manga_metadata("x", VolumeRef.volume(Decimal(1)), ANILIST, Directives(), 2)
        self.assertEqual((meta.subject_id, meta.web_url), (None, "https://anilist.co/manga/30002"))
        self.assertIn(b"<Web>https://anilist.co/manga/30002</Web>", build_comic_info(meta, 3))
        self.assertEqual(metadata_from_json("manga", metadata_to_json(meta)), meta)

    def test_bangumi_comicinfo_metadata_is_as_before(self):
        meta = manga_metadata("x", VolumeRef.volume(Decimal(1)), SUBJECT, Directives(), 2)
        data = metadata_to_json(meta)
        self.assertEqual(data["subject_id"], 279379)
        self.assertNotIn("web_url", data)
        self.assertIn(b"<Web>https://bgm.tv/subject/279379</Web>", build_comic_info(meta, 3))

    def test_anilist_web_link_in_epub(self):
        meta = novel_metadata("x", NovelVolume.volume(Decimal(1)), ANILIST, {}, Directives(),
                              first_volume=True, fallback_title="stem")
        self.assertEqual(meta.web_url, "https://anilist.co/manga/30002")

    def test_bgm_template_var_empty_for_anilist(self):
        self.assertEqual(bangumi_id(SUBJECT), "279379")
        self.assertIsNone(bangumi_id(ANILIST))
        self.assertIsNone(bangumi_id(Subject.unlisted("书")))

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

    def test_novel_carries_the_illustrators_and_survives_a_round_trip(self):
        subject = replace(SUBJECT, illustrators=("ももこ",))
        meta = novel_metadata("x", NovelVolume.volume(Decimal(1)), subject, {}, Directives(),
                              first_volume=True, fallback_title="f")
        self.assertEqual(meta.illustrators, ("ももこ",))
        self.assertEqual(metadata_from_json("novel", metadata_to_json(meta)), meta)

    def test_novel_plans_from_before_illustrators_still_load(self):
        meta = novel_metadata("x", NovelVolume.volume(Decimal(1)), SUBJECT, {}, Directives(),
                              first_volume=True, fallback_title="f")
        stored = metadata_to_json(meta)
        stored.pop("illustrators", None)
        self.assertEqual(metadata_from_json("novel", stored).illustrators, ())

    def test_volume_from_key(self):
        self.assertEqual(volume_from_key("manga", "range:1-5"), VolumeRef.range(Decimal(1), Decimal(5)))
        self.assertEqual(volume_from_key("manga", "special:2"), VolumeRef.special(2))
        self.assertEqual(volume_from_key("manga", "chapter:1-40"), VolumeRef.chapter(Decimal(1), Decimal(40)))
        self.assertEqual(volume_from_key("novel", "special"), NovelVolume.special())
        self.assertEqual(volume_from_key("novel", "volume:7.5"), NovelVolume.volume(Decimal("7.5")))


if __name__ == "__main__":
    unittest.main()
