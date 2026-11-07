from decimal import Decimal
from pathlib import Path
import unittest

from shutong.engine.kinds.manga.adapter import default_relative_target as manga_target
from shutong.engine.kinds.manga.volume import VolumeRef
from shutong.engine.kinds.novel.adapter import default_relative_target as novel_target
from shutong.engine.kinds.novel.naming import NovelVolume
from shutong.engine.template import DEFAULT_TEMPLATE, TemplateError, render, validate_template


class TemplateTests(unittest.TestCase):
    def test_default_reproduces_legacy_manga_and_novel_names(self):
        volume = VolumeRef.volume(Decimal("1.5"))
        self.assertEqual(
            render(DEFAULT_TEMPLATE, {"series": "间谍过家家[东立电子版]", "volume": volume.token(2), "ext": ".cbz"}),
            manga_target("间谍过家家[东立电子版]", volume),
        )
        self.assertEqual(
            render(DEFAULT_TEMPLATE, {"series": "86", "volume": "SP02", "ext": ".epub"}),
            novel_target("86", NovelVolume.special(), special_index=2),
        )
        self.assertEqual(
            render(DEFAULT_TEMPLATE, {"series": "86", "volume": "Vol.07.5", "ext": ".epub"}),
            novel_target("86", NovelVolume.volume(Decimal("7.5"))),
        )

    def test_conditional_format(self):
        template = "{title}{edition:[%s]}/{title} {volume}{ext}"
        self.assertEqual(render(template, {"title": "迷宫饭", "edition": None, "volume": "Vol.01", "ext": ".cbz"}),
                         Path("迷宫饭/迷宫饭 Vol.01.cbz"))
        self.assertEqual(render(template, {"title": "迷宫饭", "edition": "bili电子版", "volume": "Vol.01",
                                           "ext": ".cbz"}),
                         Path("迷宫饭[bili电子版]/迷宫饭 Vol.01.cbz"))

    def test_custom_template_with_year_and_bgm(self):
        template = "{series}{year: (%s)}/{series} {volume}{bgm: [bgm%s]}{ext}"
        self.assertEqual(render(template, {"series": "迷宫饭", "year": "2014", "bgm": "133315",
                                           "volume": "Vol.01", "ext": ".cbz"}),
                         Path("迷宫饭 (2014)/迷宫饭 Vol.01 [bgm133315].cbz"))

    def test_validation_errors(self):
        for template in ("{series}/{colour}{ext}", "{series}/{volume}", "{series}/{volume:%s%s}{ext}",
                         "{series}/{volume:x}{ext}", "{series}//{volume}{ext}", "{series/{volume}{ext}", ""):
            with self.subTest(template=template), self.assertRaises(TemplateError):
                validate_template(template)
        validate_template(DEFAULT_TEMPLATE)

    def test_render_rejects_empty_segment_and_backslash(self):
        with self.assertRaises(TemplateError):
            render("{edition}/{series} {volume}{ext}", {"edition": None, "series": "a", "volume": "Vol.01", "ext": ".cbz"})
        with self.assertRaises(TemplateError):
            render(DEFAULT_TEMPLATE, {"series": "a\\b", "volume": "Vol.01", "ext": ".cbz"})


if __name__ == "__main__":
    unittest.main()
