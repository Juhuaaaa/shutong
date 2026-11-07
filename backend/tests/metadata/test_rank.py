import unittest

from shutong.metadata.base import Subject
from shutong.metadata.rank import fits_kind, is_volume_entry, pick, rank, similarity


def subject(subject_id, name_cn, *, name="", platform="", genres=(), total=None, series=None):
    return Subject(subject_id=subject_id, name=name, name_cn=name_cn, summary="", release_date=None,
                   writers=(), publisher="", genres=tuple(genres), completed=False, total_volumes=total,
                   platform=platform, series=series)


class RankTests(unittest.TestCase):
    def test_exact_and_contained_titles(self):
        self.assertEqual(similarity("迷宫饭", "迷宫饭"), 1.0)
        self.assertEqual(similarity("间谍过家家", "间谍过家家短篇"), 0.9)
        self.assertEqual(similarity("间", "间谍过家家"), 0.0)

    def test_novel_filter_uses_platform_first(self):
        self.assertTrue(fits_kind(subject(1, "x", platform="小说", genres=("漫画",)), "novel"))
        self.assertFalse(fits_kind(subject(1, "x", platform="漫画", genres=("轻小说",)), "novel"))
        self.assertTrue(fits_kind(subject(1, "x", genres=("轻小说",)), "novel"))
        self.assertTrue(fits_kind(subject(1, "x", total=3), "novel"))

    def test_manga_filter(self):
        self.assertTrue(fits_kind(subject(1, "x", platform="漫画"), "manga"))
        self.assertFalse(fits_kind(subject(1, "x", platform="小说"), "manga"))
        self.assertTrue(fits_kind(subject(1, "x", genres=("漫画",)), "manga"))
        self.assertFalse(fits_kind(subject(1, "x", genres=("漫画", "轻小说")), "manga"))
        self.assertFalse(fits_kind(subject(1, "x"), "manga"))
        self.assertTrue(fits_kind(subject(1, "x", total=5), "manga"))

    def test_rank_orders_by_score_then_volumes(self):
        ranked = rank("迷宫饭", [subject(1, "迷宫饭 外传", platform="漫画", total=1),
                                subject(2, "迷宫饭", platform="漫画", total=14),
                                subject(3, "无关", platform="漫画"),
                                subject(4, "迷宫饭", platform="小说")], "manga")
        self.assertEqual([(s.subject.subject_id, s.score) for s in ranked], [(2, 1.0), (1, 0.9)])
        self.assertEqual(pick(ranked).subject_id, 2)

    def test_name_or_name_cn(self):
        ranked = rank("ダンジョン飯", [subject(5, "迷宫饭", name="ダンジョン飯", platform="漫画")], "manga")
        self.assertEqual(ranked[0].score, 1.0)

    def test_tie_is_not_picked(self):
        ranked = rank("迷宫饭", [subject(1, "迷宫饭", platform="漫画", total=3),
                                subject(2, "迷宫饭", platform="漫画", total=3)], "manga")
        self.assertIsNone(pick(ranked))

    def test_below_threshold_not_picked(self):
        self.assertIsNone(pick(rank("迷宫饭", [subject(1, "完全不同", platform="漫画")], "manga")))
        self.assertIsNone(pick(()))

    def test_single_volume_entry_is_not_a_series(self):
        # Bangumi lists each tankobon as its own subject: 「ベルベット・キス (1)」 is volume 1, not the series.
        for name in ("ベルベット・キス (1)", "ベルベット・アーミー(2)", "天鹅绒之吻（1）", "某作品 第3巻", "某作品 5"):
            self.assertTrue(is_volume_entry(subject(1, "", name=name, platform="漫画", series=False)), name)
        self.assertFalse(fits_kind(subject(1, "", name="ベルベット・キス (1)", platform="漫画", series=False), "manga"))

    def test_series_and_one_shots_still_fit(self):
        self.assertFalse(is_volume_entry(subject(1, "", name="ベルベット・アーミー", platform="漫画", series=True)))
        self.assertFalse(is_volume_entry(subject(2, "", name="ベルベット・ナイト", platform="漫画", series=False)))
        self.assertFalse(is_volume_entry(subject(3, "", name="Level 99 (1)", platform="漫画", series=True)))
        self.assertFalse(is_volume_entry(subject(4, "", name="某作品 (1)", platform="漫画")))  # unknown: keep

    def test_rank_skips_volume_entries(self):
        ranked = rank("ベルベット・キス", [subject(1, "", name="ベルベット・キス (1)", platform="漫画", series=False)],
                      "manga")
        self.assertEqual(ranked, ())


if __name__ == "__main__":
    unittest.main()
