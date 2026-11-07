import json
import math
import unittest

from shutong.ai.openai_compat import AiError
from shutong.engine.ai_assist import SourceContext, choose_own_entry, choose_subject
from shutong.metadata.base import Subject


class FakeAi:
    """Stands in for AuditedAi: returns queued results or raises queued errors."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def complete_json(self, purpose, system, payload, *, item_id=None):
        self.requests.append({"purpose": purpose, "system": system, "payload": payload, "item_id": item_id})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome, 41


def candidate(subject_id=279379, **overrides):
    values = dict(subject_id=subject_id, name="SPY×FAMILY", name_cn="间谍过家家", summary="A family story " * 100,
                  release_date="2019-03-25", writers=("远藤达哉",), publisher="集英社", genres=("漫画",),
                  completed=False, total_volumes=None)
    values.update(overrides)
    return Subject(**values)


def context(**overrides):
    values = dict(source_folder="/media/private/间谍过家家[bili]",
                  names=("/media/private/间谍过家家[bili]/Vol.01.cbz",),
                  title_hint="间谍过家家", edition_signals=("bili电子版",))
    values.update(overrides)
    return SourceContext(**values)


class ChooseOwnEntryTests(unittest.TestCase):
    def ask(self, answer, threshold=0.85):
        ai = FakeAi(answer)
        result = choose_own_entry(ai, context(title_hint="间谍过家家 外传"), [candidate()], threshold,
                                  base_title="间谍过家家", kind="manga", item_id=7)
        return ai, result

    def test_tells_the_ai_what_counts_as_the_entry(self):
        ai, result = self.ask({"subject_id": 279379, "confidence": 0.98, "reason": "就是它"})
        self.assertEqual((result.subject_id, result.meets_threshold, result.none_found), (279379, True, False))
        self.assertEqual(ai.requests[0]["payload"]["base_title"], "间谍过家家")
        self.assertIn("original work", ai.requests[0]["system"])

    def test_a_confident_none_is_an_answer(self):
        _, result = self.ask({"subject_id": None, "confidence": 0.9, "reason": "没有"})
        self.assertEqual((result.subject_id, result.meets_threshold, result.none_found), (None, False, True))

    def test_an_unsure_none_is_not(self):
        _, result = self.ask({"subject_id": None, "confidence": 0.5, "reason": "说不准"})
        self.assertFalse(result.none_found)

    def test_an_unusable_reply_decides_nothing(self):
        _, result = self.ask({"subject_id": 1, "confidence": 0.99, "reason": "不在候选里"})
        self.assertFalse(result.meets_threshold or result.none_found)
        self.assertIsNotNone(result.problem)


class ChooseSubjectTests(unittest.TestCase):
    def test_meets_threshold_and_records_call(self):
        ai = FakeAi({"subject_id": 279379, "confidence": 0.98, "reason": "title and author"})
        result = choose_subject(ai, context(), [candidate()], 0.95, kind="manga", item_id=7)
        self.assertEqual((result.subject_id, result.meets_threshold, result.call_id, result.problem),
                         (279379, True, 41, None))
        self.assertEqual(ai.requests[0]["item_id"], 7)

    def test_payload_contains_only_basenames_and_compact_candidates(self):
        ai = FakeAi({"subject_id": 279379, "confidence": 0.98, "reason": "x"})
        long = candidate(name="x" * 1000, writers=tuple("w{0}".format(i) for i in range(100)))
        choose_subject(ai, context(), [long], 0.95, kind="manga")
        payload = ai.requests[0]["payload"]
        self.assertEqual(payload["source_folder"], "间谍过家家[bili]")
        self.assertEqual(payload["file_names"], ["Vol.01.cbz"])
        self.assertEqual(payload["normalized_title"], "间谍过家家")
        self.assertEqual(payload["edition_signals"], ["bili电子版"])
        compact = payload["candidates"][0]
        self.assertEqual(set(compact), {"subject_id", "name", "name_cn", "writers", "publisher"})
        self.assertLessEqual(len(compact["name"]), 200)
        self.assertLessEqual(len(compact["writers"]), 8)
        serialized = json.dumps(ai.requests[0], ensure_ascii=False)
        self.assertNotIn("/Volumes", serialized)
        self.assertNotIn("A family story", serialized)

    def test_kind_changes_system_prompt(self):
        manga_ai = FakeAi({"subject_id": None, "confidence": 0.1, "reason": "x"})
        novel_ai = FakeAi({"subject_id": None, "confidence": 0.1, "reason": "x"})
        choose_subject(manga_ai, context(), [candidate()], 0.95, kind="manga")
        choose_subject(novel_ai, context(), [candidate()], 0.95, kind="novel")
        self.assertIn("漫画", manga_ai.requests[0]["system"])
        self.assertIn("轻小说", novel_ai.requests[0]["system"])

    def test_no_candidates_skips_ai(self):
        ai = FakeAi()
        result = choose_subject(ai, context(), [], 0.95, kind="manga")
        self.assertEqual((result.problem, ai.requests), ("没有候选条目", []))

    def test_null_and_low_confidence_do_not_meet_threshold(self):
        for response in ({"subject_id": None, "confidence": 0.2, "reason": "none match"},
                         {"subject_id": 279379, "confidence": 0.94, "reason": "ambiguous"}):
            with self.subTest(response=response):
                result = choose_subject(FakeAi(response), context(), [candidate()], 0.95, kind="manga")
                self.assertFalse(result.meets_threshold)
                self.assertIsNone(result.problem)
                self.assertEqual(result.reason, response["reason"])

    def test_minimum_confidence_floor(self):
        result = choose_subject(FakeAi({"subject_id": 279379, "confidence": 0.79, "reason": "below floor"}),
                                context(), [candidate()], 0.5, kind="manga")
        self.assertFalse(result.meets_threshold)

    def test_invalid_responses_become_problems(self):
        for response in (
            {"subject_id": 999, "confidence": 1.0, "reason": "not offered"},
            {"subject_id": True, "confidence": 1.0, "reason": "wrong"},
            {"subject_id": 279379, "confidence": True, "reason": "wrong"},
            {"subject_id": 279379, "confidence": math.nan, "reason": "wrong"},
            {"subject_id": 279379, "confidence": 1.1, "reason": "wrong"},
            {"subject_id": 279379, "confidence": 1.0},
            {"subject_id": 279379, "confidence": 1.0, "reason": "x", "extra": 1},
            {"subject_id": 279379, "confidence": 1.0, "reason": " "},
        ):
            with self.subTest(response=response):
                result = choose_subject(FakeAi(response), context(), [candidate()], 0.95, kind="manga")
                self.assertFalse(result.meets_threshold)
                self.assertIsNotNone(result.problem)

    def test_ai_errors_become_problems_not_exceptions(self):
        result = choose_subject(FakeAi(AiError("fenced")), context(), [candidate()], 0.95, kind="manga")
        self.assertEqual((result.problem, result.meets_threshold), ("AI 调用失败或返回的内容不符合要求", False))
