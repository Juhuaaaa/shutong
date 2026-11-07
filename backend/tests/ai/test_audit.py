from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from shutong.ai.audit import AuditedAi
from shutong.ai.openai_compat import AiError
from shutong.store.ai_calls import AiCallStore
from shutong.store.db import Database


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 29, 23, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class FakeProvider:
    model = "m-1"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def complete_json(self, system, payload):
        self.requests.append((system, payload))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome, '{"raw": true}'


class AuditTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        db = Database(Path(self._directory.name) / "shutong.db")
        db.migrate()
        self.clock = Clock()
        self.calls = AiCallStore(db, clock=self.clock)

    def test_success_and_failure_are_both_audited(self):
        provider = FakeProvider([{"subject_id": 1}, AiError("bad json", raw="```oops```")])
        ai = AuditedAi(provider, self.calls, clock=self.clock)
        result, call_id = ai.complete_json("choose_subject", "s", {"names": ["a"]})
        self.assertEqual(result, {"subject_id": 1})
        with self.assertRaises(AiError):
            ai.complete_json("choose_subject", "s", {"names": ["b"]})
        with self.calls.db.connect() as connection:
            rows = connection.execute("SELECT id, model, response_text, error, request_json FROM ai_calls ORDER BY id").fetchall()
        self.assertEqual(rows[0]["id"], call_id)
        self.assertEqual((rows[0]["model"], rows[0]["error"], rows[0]["response_text"]), ("m-1", None, '{"raw": true}'))
        self.assertEqual((rows[1]["response_text"], rows[1]["error"]), ("```oops```", "bad json"))
        self.assertIn('"b"', rows[1]["request_json"])

    def test_no_daily_limit(self):
        provider = FakeProvider([{"a": n} for n in range(300)])
        ai = AuditedAi(provider, self.calls, clock=self.clock)
        for _ in range(300):
            ai.complete_json("p", "s", {})
        self.assertEqual(len(provider.requests), 300)

    def test_unexpected_provider_errors_are_audited_and_wrapped(self):
        provider = FakeProvider([ValueError("unknown url type: 'api.deepseek.com/chat/completions'")])
        ai = AuditedAi(provider, self.calls, clock=self.clock)
        with self.assertRaises(AiError):
            ai.complete_json("p", "s", {})
        with self.calls.db.connect() as connection:
            row = connection.execute("SELECT error FROM ai_calls").fetchone()
        self.assertIn("unknown url type", row["error"])


if __name__ == "__main__":
    unittest.main()
