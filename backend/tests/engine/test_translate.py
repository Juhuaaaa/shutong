from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from shutong.ai.openai_compat import AiError
from shutong.engine.translate import localize
from shutong.metadata.base import Subject
from shutong.store.cache import CacheStore
from shutong.store.db import Database

BERSERK = Subject(subject_id="30002", name="ベルセルク", name_cn="", summary="Guts, a former mercenary, fights demons.",
                  release_date=None, writers=(), publisher="", genres=(), completed=False, total_volumes=None,
                  source="anilist", aliases=("Berserk",))


class Translator:
    def __init__(self, answer=None, error=None):
        self.calls = []
        self.answer = answer if answer is not None else {"summary": "前佣兵格斯与恶魔战斗。"}
        self.error = error

    def complete_json(self, purpose, system, payload, *, item_id=None):
        self.calls.append((purpose, payload))
        if self.error:
            raise self.error
        return self.answer, 3


class LocalizeTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        db = Database(Path(self._directory.name) / "s.db")
        db.migrate()
        self.cache = CacheStore(db)

    def test_an_english_summary_is_translated_once(self):
        ai = Translator()
        first = localize(BERSERK, ai=ai, cache=self.cache, enabled=True)
        again = localize(BERSERK, ai=ai, cache=self.cache, enabled=True)
        self.assertEqual((first.summary, again.summary), ("前佣兵格斯与恶魔战斗。", "前佣兵格斯与恶魔战斗。"))
        self.assertEqual(len(ai.calls), 1)
        self.assertEqual(ai.calls[0][0], "translate")
        self.assertEqual(ai.calls[0][1]["summary"], BERSERK.summary)
        self.assertEqual(first.name, BERSERK.name)

    def test_left_alone(self):
        ai = Translator()
        bangumi = replace(BERSERK, source="bangumi", summary="格斯的故事。")
        cases = {
            "switched off": (BERSERK, False, ai),
            "no AI": (BERSERK, True, None),
            "Chinese already": (replace(BERSERK, summary="格斯是前佣兵，与恶魔战斗。"), True, ai),
            "Bangumi": (bangumi, True, ai),
            "Bangumi in Japanese": (replace(bangumi, summary="ガッツは元傭兵。"), True, ai),
            "no summary": (replace(BERSERK, summary=""), True, ai),
        }
        for name, (subject, enabled, model) in cases.items():
            with self.subTest(name):
                self.assertIs(localize(subject, ai=model, cache=self.cache, enabled=enabled), subject)
        self.assertEqual(ai.calls, [])

    def test_a_failed_translation_keeps_the_original(self):
        for ai in (Translator(error=AiError("timed out")), Translator(answer={"summary": ""}),
                   Translator(answer={"text": "x"})):
            with self.subTest(answer=ai.answer, error=ai.error):
                self.assertIs(localize(BERSERK, ai=ai, cache=self.cache, enabled=True), BERSERK)

    def test_a_changed_summary_is_translated_again(self):
        ai = Translator()
        localize(BERSERK, ai=ai, cache=self.cache, enabled=True)
        localize(replace(BERSERK, summary="New text."), ai=ai, cache=self.cache, enabled=True)
        self.assertEqual(len(ai.calls), 2)


if __name__ == "__main__":
    unittest.main()
