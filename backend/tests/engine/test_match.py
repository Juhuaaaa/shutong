import io
import unittest
from urllib.error import HTTPError

from shutong.engine.ai_assist import SourceContext
from shutong.engine.match import match_subject
from shutong.metadata.base import MetadataUnavailable, Subject

from .test_ai_assist import FakeAi


def subject(subject_id, name_cn, platform="漫画", total=None, name="", series=None):
    return Subject(subject_id=subject_id, name=name, name_cn=name_cn, summary="", release_date=None, writers=(),
                   publisher="", genres=(), completed=False, total_volumes=total, platform=platform, series=series)


class FakeSource:
    name = "fake"

    def __init__(self, results=(), subjects=None, error=None):
        self.results = tuple(results)
        self.subjects = subjects or {}
        self.error = error
        self.searches = []
        self.gets = []

    def search(self, query, kind):
        self.searches.append((query, kind))
        if self.error:
            raise self.error
        return self.results

    def get(self, subject_id, *, fresh=False):
        self.gets.append((subject_id, fresh))
        if self.error:
            raise self.error
        return self.subjects[subject_id]


class ByQuery(FakeSource):
    def __init__(self, answers):
        super().__init__()
        self.answers = answers

    def search(self, query, kind):
        self.searches.append((query, kind))
        return self.answers.get(query, ())


CONTEXT = SourceContext(source_folder="迷宫饭", names=("Vol.01.zip",), title_hint="迷宫饭")


class MatchTests(unittest.TestCase):
    def test_forced_bgm_skips_search(self):
        source = FakeSource(subjects={133315: subject(133315, "迷宫饭")})
        result = match_subject(source, kind="manga", title_hint="迷宫饭", forced_bgm=133315)
        self.assertEqual((result.subject.subject_id, result.method, source.searches), (133315, "rule", []))

    def test_auto_pick(self):
        source = FakeSource([subject(1, "迷宫饭 外传"), subject(2, "迷宫饭", total=14)])
        result = match_subject(source, kind="manga", title_hint="迷宫饭", forced_bgm=None)
        self.assertEqual((result.subject.subject_id, result.method, result.retry), (2, "auto", False))
        self.assertEqual([s.subject.subject_id for s in result.candidates], [2, 1])
        self.assertEqual(source.searches, [("迷宫饭", "manga")])

    def test_a_namesake_in_the_other_kind_leads_to_the_right_entry(self):
        # Bangumi calls the novel 我的女友老师: its Chinese name misses, but the manga of that name has the original.
        manga = subject(280628, "我的女友是老师", name="僕のカノジョ先生", platform="漫画")
        novel = subject(276153, "我的女友老师", name="僕のカノジョ先生", platform="小说", total=9)
        other = subject(535957, "我的女友是恶女", platform="小说")
        source = ByQuery({"我的女友是老师": (manga, other), "僕のカノジョ先生": (novel, manga)})
        result = match_subject(source, kind="novel", title_hint="我的女友是老师", forced_bgm=None, context=CONTEXT,
                               ai=FakeAi({"subject_id": None, "confidence": 0.99, "reason": "不是"}))
        self.assertEqual((result.subject.subject_id, result.method), (276153, "auto"))
        self.assertEqual([query for query, _ in source.searches], ["我的女友是老师", "僕のカノジョ先生"])

    def test_a_namesake_with_another_title_leads_nowhere(self):
        manga = subject(1, "完全不同", name="全然違う", platform="漫画")
        source = ByQuery({"我的女友是老师": (manga,)})
        match_subject(source, kind="novel", title_hint="我的女友是老师", forced_bgm=None)
        self.assertEqual([query for query, _ in source.searches], ["我的女友是老师"])

    def test_ai_fallback_meets_threshold(self):
        source = FakeSource([subject(1, "完全不同"), subject(2, "也不同")])
        ai = FakeAi({"subject_id": 2, "confidence": 0.99, "reason": "作者一致"})
        result = match_subject(source, kind="manga", title_hint="迷宫饭", forced_bgm=None, context=CONTEXT, ai=ai)
        self.assertEqual((result.subject.subject_id, result.method, result.suggestion.reason), (2, "ai", "作者一致"))
        self.assertEqual({c["subject_id"] for c in ai.requests[0]["payload"]["candidates"]}, {1, 2})

    def test_ai_below_threshold_returns_suggestion_only(self):
        source = FakeSource([subject(1, "完全不同")])
        ai = FakeAi({"subject_id": 1, "confidence": 0.5, "reason": "不确定"})
        result = match_subject(source, kind="manga", title_hint="迷宫饭", forced_bgm=None, context=CONTEXT, ai=ai)
        self.assertEqual((result.subject, result.method, result.suggestion.subject_id), (None, "none", 1))

    def test_ai_receives_kind_filtered_candidates_when_any(self):
        source = FakeSource([subject(1, "迷宫", platform="漫画"), subject(2, "迷宫", platform="小说")])
        ai = FakeAi({"subject_id": None, "confidence": 0.1, "reason": "x"})
        match_subject(source, kind="manga", title_hint="迷宫饭的日常", forced_bgm=None, context=CONTEXT, ai=ai)
        self.assertEqual([c["subject_id"] for c in ai.requests[0]["payload"]["candidates"]], [1])

    def test_single_volume_entries_are_never_offered(self):
        # 天鹅绒之吻: Bangumi only returned volume 1 (the series is hidden from anonymous calls).
        source = FakeSource([subject(20244, "", name="ベルベット・キス (1)", series=False),
                             subject(159438, "", name="ベルベット・ナイト", platform="小说", series=False)])
        ai = FakeAi({"subject_id": 20244, "confidence": 0.99, "reason": "x"})
        result = match_subject(source, kind="manga", title_hint="天鹅绒之吻", forced_bgm=None,
                               search_titles=("ベルベット・キス",), context=CONTEXT, ai=ai)
        self.assertIsNone(result.subject)
        self.assertNotIn(20244, [s.subject_id for s in result.offered])
        for request in ai.requests:
            self.assertNotIn(20244, [c["subject_id"] for c in request["payload"]["candidates"]])

    def test_no_ai_configured_is_none(self):
        result = match_subject(FakeSource([subject(1, "完全不同")]), kind="manga", title_hint="迷宫饭", forced_bgm=None)
        self.assertEqual((result.subject, result.method, result.suggestion, result.retry), (None, "none", None, False))

    def test_unavailable_source_means_retry_not_review(self):
        source = FakeSource(error=MetadataUnavailable("Bangumi unavailable after 3 attempts"))
        result = match_subject(source, kind="manga", title_hint="迷宫饭", forced_bgm=None, context=CONTEXT,
                               ai=FakeAi())
        self.assertEqual((result.retry, result.method, result.subject), (True, "none", None))
        self.assertIn("unavailable", result.error)

    def test_forced_bgm_unavailable_is_retry(self):
        source = FakeSource(error=MetadataUnavailable("down"))
        result = match_subject(source, kind="manga", title_hint="迷宫饭", forced_bgm=1)
        self.assertTrue(result.retry)

    def test_missing_subject_goes_to_review_with_error(self):
        source = FakeSource(error=HTTPError("https://api.bgm.tv/v0/subjects/9", 404, "Not Found", {}, io.BytesIO()))
        result = match_subject(source, kind="manga", title_hint="迷宫饭", forced_bgm=9)
        self.assertEqual((result.method, result.retry, result.config_error), ("none", False, False))
        self.assertEqual(result.error, "Bangumi 返回错误：404 Not Found")

    def test_auth_failure_is_a_configuration_error(self):
        for code in (401, 403):
            with self.subTest(code=code):
                source = FakeSource(error=HTTPError("https://api.bgm.tv", code, "no", {}, io.BytesIO()))
                result = match_subject(source, kind="manga", title_hint="迷宫饭", forced_bgm=None)
                self.assertEqual((result.method, result.retry, result.config_error), ("none", False, True))

    def test_malformed_response_is_an_error_not_a_crash(self):
        result = match_subject(FakeSource(error=ValueError("Bangumi response is not valid JSON")),
                               kind="manga", title_hint="迷宫饭", forced_bgm=None)
        self.assertEqual((result.method, result.retry), ("none", False))
        self.assertIn("JSON", result.error)

    def test_blank_title_skips_search(self):
        source = FakeSource()
        result = match_subject(source, kind="manga", title_hint="  ", forced_bgm=None)
        self.assertEqual((result.method, source.searches), ("none", []))
        self.assertEqual(result.error, "没有书名，无法搜索 Bangumi")


if __name__ == "__main__":
    unittest.main()
