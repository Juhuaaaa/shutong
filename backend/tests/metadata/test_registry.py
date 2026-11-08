import unittest

from shutong.metadata.base import Subject, SubjectRef, web_url_for
from shutong.metadata.registry import KNOWN_SOURCES, LABELS, SourceRegistry


class Named:
    def __init__(self, name):
        self.name = name
        self.label = name.title()


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = Named("bangumi"), Named("anilist")
        self.sources = {"bangumi": self.a, "anilist": self.b}

    def test_enabled_follows_setting_order(self):
        registry = SourceRegistry(self.sources, ["anilist", "bangumi"])
        self.assertEqual(registry.enabled, (self.b, self.a))
        self.assertIs(registry.primary, self.b)

    def test_registry_ignores_unknown_and_falls_back(self):
        self.assertEqual(SourceRegistry(self.sources, ["douban"]).enabled, (self.a,))
        self.assertEqual(SourceRegistry(self.sources, ["douban", "anilist"]).enabled, (self.b,))
        self.assertEqual(SourceRegistry(self.sources, None).enabled, (self.a,))
        self.assertEqual(SourceRegistry(self.sources, "bangumi").enabled, (self.a,))

    def test_get_disabled_source_still_works(self):
        registry = SourceRegistry(self.sources, ["bangumi"])
        self.assertIs(registry.get("anilist"), self.b)
        with self.assertRaises(KeyError):
            registry.get("douban")

    def test_single(self):
        fake = Named("fake")
        registry = SourceRegistry.single(fake)
        self.assertEqual(registry.enabled, (fake,))
        self.assertIs(registry.get("fake"), fake)

    def test_known_sources(self):
        self.assertEqual(KNOWN_SOURCES, ("bangumi", "anilist"))
        self.assertEqual(LABELS, {"bangumi": "Bangumi", "anilist": "AniList"})


class SubjectRefTests(unittest.TestCase):
    def test_from_overrides(self):
        self.assertEqual(SubjectRef.from_overrides({"bgm": 123}), SubjectRef("bangumi", "123"))
        ref = SubjectRef.from_overrides({"subject": {"source": "anilist", "id": 30002}, "bgm": 1})
        self.assertEqual(ref, SubjectRef("anilist", "30002"))
        self.assertIsNone(SubjectRef.from_overrides({}))
        self.assertIsNone(SubjectRef.from_overrides({"bgm": None}))

    def test_from_json_rejects_blanks(self):
        for bad in ({"source": "", "id": "1"}, {"source": "bangumi", "id": ""}, {"source": "bangumi"}, "x", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                SubjectRef.from_json(bad)

    def test_json_round_trip(self):
        ref = SubjectRef("anilist", "30002")
        self.assertEqual(ref.to_json(), {"source": "anilist", "id": "30002"})
        self.assertEqual(SubjectRef.from_json(ref.to_json()), ref)
        self.assertEqual(ref.key, "anilist:30002")

    def test_web_urls(self):
        self.assertEqual(web_url_for("anilist", "30002"), "https://anilist.co/manga/30002")
        self.assertEqual(web_url_for("bangumi", "439286"), "https://bgm.tv/subject/439286")
        self.assertEqual(web_url_for("none", ""), "")
        self.assertEqual(web_url_for("bangumi", ""), "")

    def test_subject_id_is_text(self):
        subject = Subject(subject_id=7, name="a", name_cn="", summary="", release_date=None, writers=(),
                          publisher="", genres=(), completed=False, total_volumes=None)
        self.assertEqual(subject.subject_id, "7")
        self.assertEqual(subject.ref, SubjectRef("bangumi", "7"))
        self.assertEqual(subject.web_url, "https://bgm.tv/subject/7")
        self.assertEqual(Subject.unlisted("书").subject_id, "")
        self.assertEqual(Subject.unlisted("书").web_url, "")

    def test_display_title_prefers_aliases_over_native(self):
        subject = Subject(subject_id="1", name="ベルセルク", name_cn="", summary="", release_date=None, writers=(),
                          publisher="", genres=(), completed=False, total_volumes=None,
                          aliases=("Berserk",), source="anilist")
        self.assertEqual(subject.display_title, "Berserk")


if __name__ == "__main__":
    unittest.main()
