from shutong.ai.openai_compat import Usage
from shutong.store.ai_calls import AiCallStore

from .helpers import ApiCase


class AiUsageTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_adds_up_the_tokens_of_every_call(self):
        store = AiCallStore(self.app.state.db)
        for usage in (Usage(prompt=2000, completion=300, cached=1500), None):
            store.record(item_id=None, purpose="recognize", model="m", request_json="{}", response_text="{}",
                         error=None, duration_ms=1, usage=usage)
        response = self.client.get("/api/ai/usage")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"calls": 2, "measured": 1, "prompt_tokens": 2000,
                                           "completion_tokens": 300, "cached_tokens": 1500})
