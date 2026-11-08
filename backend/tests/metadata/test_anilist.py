import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from shutong.metadata.anilist import AniListSource
from shutong.metadata.bangumi import USER_AGENT
from shutong.metadata.base import MetadataUnavailable
from shutong.store.cache import CacheStore
from shutong.store.db import Database

from .test_bangumi import FakeResponse

KAGUYA = {
    "id": 86635,
    "title": {"romaji": "Kaguya-sama wa Kokurasetai", "english": "Kaguya-sama: Love is War",
              "native": "かぐや様は告らせたい～天才たちの恋愛頭脳戦～"},
    "synonyms": ["Kaguya Wants to be Confessed To", "Kaguya-sama: Love is War"],
    "description": "Two geniuses.<br>\n<i>Who confesses</i> first? (Source: Viz)",
    "startDate": {"year": 2015, "month": 5, "day": 19},
    "status": "FINISHED",
    "volumes": 28,
    "genres": ["Comedy", "Romance"],
    "format": "MANGA",
    "coverImage": {"large": "https://s4.anilist.co/file/cover.jpg"},
    "staff": {"edges": [
        {"role": "Story & Art", "node": {"name": {"full": "Aka Akasaka", "native": "赤坂アカ"}}},
        {"role": "Assistant", "node": {"name": {"full": "Someone", "native": "誰か"}}},
        {"role": "Illustration", "node": {"name": {"full": "Momoco", "native": "ももこ"}}},
    ]},
}

BARE = {"id": 5, "title": {"romaji": "Hadaka", "english": None, "native": None}, "synonyms": None,
        "description": None, "startDate": {"year": None, "month": None, "day": None}, "status": None,
        "volumes": None, "genres": None, "format": "NOVEL", "coverImage": None, "staff": None}


def page(*media):
    return {"data": {"Page": {"media": list(media)}}}


class Recorder:
    """An opener answering with queued responses (or raising queued errors) and keeping the requests."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer)

    def body(self, index=0):
        return json.loads(self.requests[index].data.decode("utf-8"))


class AniListTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        db = Database(Path(self._directory.name) / "shutong.db")
        db.migrate()
        self.cache = CacheStore(db)
        self.sleeps = []

    def source(self, opener):
        return AniListSource(self.cache, opener=opener, sleep=self.sleeps.append)

    def test_search_maps_fields(self):
        subject = self.source(Recorder(page(KAGUYA))).search("かぐや様は告らせたい", "manga")[0]
        self.assertEqual(subject.subject_id, "86635")
        self.assertEqual(subject.source, "anilist")
        self.assertEqual(subject.name, "かぐや様は告らせたい～天才たちの恋愛頭脳戦～")
        self.assertEqual(subject.name_cn, "")
        self.assertEqual(subject.aliases[:3], ("Kaguya-sama: Love is War", "Kaguya-sama wa Kokurasetai",
                                               "Kaguya Wants to be Confessed To"))
        self.assertEqual(len(subject.aliases), 3)  # the synonym equal to the English title is not repeated
        self.assertEqual(subject.display_title, "Kaguya-sama: Love is War")
        self.assertEqual(subject.writers, ("赤坂アカ",))
        self.assertEqual(subject.illustrators, ("ももこ",))
        self.assertEqual(subject.release_date, "2015-05-19")
        self.assertEqual((subject.completed, subject.total_volumes, subject.series), (True, 28, True))
        self.assertEqual(subject.platform, "漫画")
        self.assertEqual(subject.genres, ("Comedy", "Romance"))
        self.assertEqual(subject.publisher, "")
        self.assertEqual(subject.image, "https://s4.anilist.co/file/cover.jpg")
        self.assertEqual(subject.web_url, "https://anilist.co/manga/86635")

    def test_novel_kind_requests_novel_format(self):
        recorder = Recorder(page(), page())
        source = self.source(recorder)
        source.search("x", "novel")
        source.search("x", "manga")
        self.assertEqual(recorder.body(0)["variables"]["formats"], ["NOVEL"])
        self.assertEqual(recorder.body(1)["variables"]["formats"], ["MANGA", "ONE_SHOT"])
        self.assertEqual(recorder.body(0)["variables"]["search"], "x")

    def test_request_sends_user_agent(self):
        recorder = Recorder(page())
        self.source(recorder).search("x", "manga")
        request = recorder.requests[0]
        self.assertEqual(request.full_url, "https://graphql.anilist.co")
        self.assertEqual(request.get_header("User-agent"), USER_AGENT)
        self.assertEqual(request.get_method(), "POST")

    def test_summary_strips_html(self):
        subject = self.source(Recorder(page(dict(KAGUYA, description="A<br>\nB <i>C</i> &amp; D (Source: X)"))))\
            .search("x", "manga")[0]
        self.assertEqual(subject.summary, "A\nB C & D")

    def test_retries_429_then_unavailable(self):
        busy = [HTTPError("https://graphql.anilist.co", 429, "slow down", {"Retry-After": "7"}, io.BytesIO())
                for _ in range(3)]
        with self.assertRaises(MetadataUnavailable):
            self.source(Recorder(*busy)).search("x", "manga")
        self.assertEqual(self.sleeps, [7, 7])

    def test_retry_then_success(self):
        busy = HTTPError("https://graphql.anilist.co", 503, "busy", {}, io.BytesIO())
        subjects = self.source(Recorder(busy, page(KAGUYA))).search("x", "manga")
        self.assertEqual(len(subjects), 1)
        self.assertEqual(self.sleeps, [1])

    def test_forbidden_is_raised_as_is(self):
        with self.assertRaises(HTTPError):
            self.source(Recorder(HTTPError("u", 403, "no", {}, io.BytesIO()))).search("x", "manga")

    def test_null_fields_map_to_empty(self):
        subject = self.source(Recorder(page(BARE))).search("x", "novel")[0]
        self.assertEqual((subject.name, subject.aliases, subject.display_title), ("Hadaka", (), "Hadaka"))
        self.assertEqual((subject.summary, subject.release_date, subject.writers, subject.genres),
                         ("", None, (), ()))
        self.assertEqual((subject.completed, subject.total_volumes, subject.platform, subject.image),
                         (False, None, "小说", ""))

    def test_get_missing_raises_keyerror(self):
        missing = HTTPError("u", 404, "Not Found", {}, io.BytesIO(b'{"errors":[{"status":404}],"data":{"Media":null}}'))
        with self.assertRaises(KeyError):
            self.source(Recorder(missing)).get("999999999")
        with self.assertRaises(KeyError):
            self.source(Recorder({"data": {"Media": None}})).get("999999999")

    def test_get_and_fresh(self):
        recorder = Recorder({"data": {"Media": KAGUYA}}, {"data": {"Media": dict(KAGUYA, volumes=29)}})
        source = self.source(recorder)
        self.assertEqual(source.get("86635").total_volumes, 28)
        self.assertEqual(source.get("86635").total_volumes, 28)  # cached
        self.assertEqual(source.get("86635", fresh=True).total_volumes, 29)
        self.assertEqual(len(recorder.requests), 2)
        self.assertEqual(recorder.body(0)["variables"], {"id": 86635})

    def test_get_rejects_non_numeric_ids(self):
        with self.assertRaises(KeyError):
            self.source(Recorder()).get("abc")

    def test_search_is_cached(self):
        recorder = Recorder(page(KAGUYA))
        source = self.source(recorder)
        source.search(" かぐや ", "manga")
        source.search("かぐや", "manga")
        self.assertEqual(len(recorder.requests), 1)


if __name__ == "__main__":
    unittest.main()
