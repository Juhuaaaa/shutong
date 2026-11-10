from decimal import Decimal
import unittest

from shutong.ai.openai_compat import AiError
from shutong.engine.ai_recognize import BATCH_SIZE, SYSTEM_PROMPT, batches, read_batch, SeriesReading

from .test_ai_assist import FakeAi


def series(**overrides):
    values = dict(id="s1", title="迷宫饭", edition="bili电子版", search_titles=["ダンジョン飯"], confidence=0.97,
                  reason="目录名第二个方括号是书名")
    values.update(overrides)
    return values


def file(name, number="1", **overrides):
    values = dict(name=name, series="s1", unit="volume", number=number, end=None, label="", confidence=0.96)
    values.update(overrides)
    return values


class ReadBatchTests(unittest.TestCase):
    def test_reads_series_and_volumes(self):
        ai = FakeAi({"series": [series()], "files": [file("Vol.01.zip"), file("Vol.02-05.zip", "2", end="5")]})
        result = read_batch(ai, kind="manga", folder="[九井谅子][迷宫饭][bili]", names=["Vol.01.zip", "Vol.02-05.zip"],
                            library_series=["迷宫饭[bili电子版]"], library_editions=["bili电子版"])
        first, second = result["Vol.01.zip"], result["Vol.02-05.zip"]
        self.assertEqual((first.series.title, first.series.edition, first.series.search_titles),
                         ("迷宫饭", "bili电子版", ("ダンジョン飯",)))
        self.assertEqual((first.file.unit, first.file.number, first.file.end), ("volume", Decimal("1"), None))
        self.assertEqual((second.file.number, second.file.end), (Decimal("2"), Decimal("5")))
        payload = ai.requests[0]["payload"]
        self.assertEqual(ai.requests[0]["purpose"], "recognize")
        self.assertEqual((payload["folder"], payload["files"], payload["library_series"]),
                         ("[九井谅子][迷宫饭][bili]", ["Vol.01.zip", "Vol.02-05.zip"], ["迷宫饭[bili电子版]"]))
        self.assertNotIn("settled_series", payload)

    def test_settled_series_and_file_facts_are_sent(self):
        ai = FakeAi({"series": [series()], "files": [file("a.epub")]})
        settled = SeriesReading("迷宫饭", None, ("ダンジョン飯",), 0.97, "前一批")
        read_batch(ai, kind="novel", folder="x", names=["a.epub"], settled=[settled],
                   facts={"a.epub": {"title": "迷宫饭 1", "creators": ("九井谅子",)}})
        payload = ai.requests[0]["payload"]
        self.assertEqual(payload["settled_series"][0]["title"], "迷宫饭")
        self.assertEqual(payload["file_facts"], {"a.epub": {"title": "迷宫饭 1", "creators": ["九井谅子"]}})
        self.assertEqual(payload["kind"], "轻小说")

    def test_a_sub_series_names_the_original_and_later_batches_are_told(self):
        ai = FakeAi({"series": [series(title="迷宫饭 外传", base_title="迷宫饭")], "files": [file("a.zip")]})
        reading = read_batch(ai, kind="manga", folder="x", names=["a.zip"])["a.zip"].series
        self.assertEqual((reading.title, reading.base_title), ("迷宫饭 外传", "迷宫饭"))
        self.assertIn("base_title", ai.requests[0]["system"])
        ai = FakeAi({"series": [series()], "files": [file("a.zip")]})
        read_batch(ai, kind="manga", folder="x", names=["a.zip"], settled=[reading])
        self.assertEqual(ai.requests[0]["payload"]["settled_series"][0]["base_title"], "迷宫饭")

    def test_later_batches_may_name_a_new_work(self):
        # A folder of several works: the first batch's works must not swallow the files of the next.
        self.assertNotIn("不要改", SYSTEM_PROMPT)
        self.assertIn("不属于其中任何一部", SYSTEM_PROMPT)

    def test_novels_are_told_there_are_no_editions_and_any_answer_is_dropped(self):
        ai = FakeAi({"series": [series(edition="台版")], "files": [file("a.epub")]})
        reading = read_batch(ai, kind="novel", folder="x", names=["a.epub"], library_editions=["东立"])["a.epub"]
        self.assertIsNone(reading.series.edition)
        self.assertEqual(ai.requests[0]["payload"]["library_editions"], [])
        self.assertIn("轻小说", SYSTEM_PROMPT)

    def test_base_title_is_optional_and_never_the_title_itself(self):
        for extra in ({}, {"base_title": None}, {"base_title": ""}, {"base_title": "迷宫饭"}):
            ai = FakeAi({"series": [series(**extra)], "files": [file("a.zip")]})
            self.assertIsNone(read_batch(ai, kind="manga", folder="x", names=["a.zip"])["a.zip"].series.base_title, extra)

    def test_slashes_in_names_become_full_width(self):
        ai = FakeAi({"series": [series(title="Fate/Zero", edition="a/b", base_title="Fate/stay night")],
                     "files": [file("a.zip")]})
        reading = read_batch(ai, kind="manga", folder="x", names=["a.zip"])["a.zip"].series
        self.assertEqual((reading.title, reading.edition, reading.base_title),
                         ("Fate／Zero", "a／b", "Fate／stay night"))

    def test_an_unusable_base_title_is_rejected(self):
        ai = FakeAi({"series": [series(base_title="..")], "files": [file("a.zip")]})
        self.assertIn("不符合要求", read_batch(ai, kind="manga", folder="x", names=["a.zip"])["a.zip"].problem)

    def test_missing_file_gets_a_problem(self):
        ai = FakeAi({"series": [series()], "files": [file("a.zip")]})
        result = read_batch(ai, kind="manga", folder="x", names=["a.zip", "b.zip"])
        self.assertIsNone(result["a.zip"].problem)
        self.assertEqual(result["b.zip"].problem, "AI 没有给出这个文件的结果")
        self.assertFalse(result["b.zip"].retry)

    def test_invalid_reply_marks_every_name(self):
        for reply in ({"series": [series(title="..")], "files": [file("a.zip")]},
                      {"series": [series()], "files": [file("a.zip", unit="book")]},
                      {"series": [series()], "files": [file("a.zip", number="-1")]},
                      {"series": [series(confidence=2)], "files": [file("a.zip")]},
                      {"files": []}):
            with self.subTest(reply=reply):
                result = read_batch(FakeAi(reply), kind="manga", folder="x", names=["a.zip"])
                self.assertIn("AI 返回的内容不符合要求", result["a.zip"].problem)
                self.assertFalse(result["a.zip"].retry)

    def test_extra_fields_are_ignored_and_optional_ones_default(self):
        reply = {"series": [{"id": "s1", "title": "怪兽8号", "confidence": 0.98, "note": "多余"}],
                 "files": [{"name": "a.zip", "series": "s1", "unit": "special", "number": "1",
                            "confidence": 0.9, "reason": "多余的说明"}],
                 "summary": "多余"}
        result = read_batch(FakeAi(reply), kind="manga", folder="x", names=["a.zip"])
        reading = result["a.zip"]
        self.assertIsNone(reading.problem)
        self.assertEqual((reading.series.title, reading.series.edition, reading.series.search_titles,
                          reading.series.reason), ("怪兽8号", None, (), ""))
        self.assertEqual((reading.file.unit, reading.file.end, reading.file.label), ("special", None, ""))

    def test_missing_essential_fields_are_still_invalid(self):
        for reply in ({"series": [{"id": "s1", "confidence": 0.9}], "files": [file("a.zip")]},
                      {"series": [series()], "files": [{"name": "a.zip", "series": "s1", "number": "1"}]},
                      {"series": [series()], "files": [{"name": "a.zip", "unit": "volume", "number": "1",
                                                       "confidence": 0.9}]}):
            with self.subTest(reply=reply):
                result = read_batch(FakeAi(reply), kind="manga", folder="x", names=["a.zip"])
                self.assertIn("AI 返回的内容不符合要求", result["a.zip"].problem)

    def test_unreachable_ai_asks_for_retry(self):
        result = read_batch(FakeAi(AiError("timed out")), kind="manga", folder="x", names=["a.zip"])
        self.assertTrue(result["a.zip"].retry)

    def test_non_json_reply_is_not_retried(self):
        result = read_batch(FakeAi(AiError("not json", raw="oops")), kind="manga", folder="x", names=["a.zip"])
        self.assertFalse(result["a.zip"].retry)
        self.assertIsNotNone(result["a.zip"].problem)

    def test_a_cut_off_reply_is_asked_again_in_halves(self):
        names = ["01.epub", "02.epub", "03.epub"]
        ai = FakeAi(AiError("not json", raw='{"series":[{"id":"s1"'),
                    {"series": [series()], "files": [file("01.epub"), file("02.epub", "2")]},
                    {"series": [series()], "files": [file("03.epub", "3")]})
        result = read_batch(ai, kind="novel", folder="x", names=names)
        self.assertEqual([request["payload"]["files"] for request in ai.requests],
                         [names, ["01.epub", "02.epub"], ["03.epub"]])
        self.assertEqual([result[name].file.number for name in names], [Decimal(1), Decimal(2), Decimal(3)])
        self.assertTrue(all(result[name].problem is None for name in names))

    def test_batches_split_long_folders(self):
        names = ["{0:04d}.zip".format(index) for index in range(BATCH_SIZE * 2 + 1)]
        self.assertEqual([len(batch) for batch in batches(names)], [BATCH_SIZE, BATCH_SIZE, 1])


class UnreadableFileTests(unittest.TestCase):
    def read(self, series, files):
        class Ai:
            def complete_json(self, purpose, system, payload, *, item_id=None):
                return {"series": series, "files": files}, 1
        return read_batch(Ai(), kind="manga", folder=None, names=[entry["name"] for entry in files])

    def test_a_file_the_ai_could_not_place_says_so_and_leaves_the_others(self):
        known = {"id": "s1", "title": "迷宫饭", "confidence": 0.9}
        file = {"unit": "volume", "number": "1", "confidence": 0.9}
        found = self.read([known], [dict(file, name="a.zip", series=None), dict(file, name="b.zip", series="s1"),
                                    dict(file, name="c.zip", series="s9")])
        self.assertIn("认不出", found["a.zip"].problem)
        self.assertIn("认不出", found["c.zip"].problem)
        self.assertEqual(found["b.zip"].series.title, "迷宫饭")

    def test_no_series_at_all(self):
        found = self.read([], [{"name": "Vol.01.cbz", "series": None, "unit": "volume", "number": "1", "confidence": 0.2}])
        self.assertIn("认不出", found["Vol.01.cbz"].problem)
        self.assertNotIn("不符合要求", found["Vol.01.cbz"].problem)
