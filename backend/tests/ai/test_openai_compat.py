import json
import unittest

from shutong.ai.openai_compat import AiError, AiSettings, OpenAICompatProvider, strict_json


class FakeResponse:
    def __init__(self, body):
        self._body = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def envelope(content):
    return {"choices": [{"message": {"content": content}}]}


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.settings = AiSettings(base_url="https://ai.example.test/v1/", api_key="ai-secret", model="m-1")

    def provider(self, body, calls=None):
        def opener(request, timeout):
            if calls is not None:
                calls.append((request, timeout))
            return FakeResponse(body)
        return OpenAICompatProvider(self.settings, opener=opener)

    def test_request_shape_and_auth_header(self):
        calls = []
        result, raw = self.provider(envelope('{"ok": true}'), calls).complete_json("系统提示", {"名字": "迷宫饭"})
        self.assertEqual((result, raw), ({"ok": True}, '{"ok": true}'))
        request, timeout = calls[0]
        self.assertEqual(request.full_url, "https://ai.example.test/v1/chat/completions")
        self.assertEqual(timeout, 60)
        self.assertEqual(request.get_header("Authorization"), "Bearer ai-secret")
        body = json.loads(request.data.decode())
        self.assertEqual((body["model"], body["temperature"], body["response_format"]),
                         ("m-1", 0, {"type": "json_object"}))
        self.assertEqual(body["messages"][0], {"role": "system", "content": "系统提示"})
        self.assertEqual(json.loads(body["messages"][1]["content"]), {"名字": "迷宫饭"})

    def test_rejects_fenced_content(self):
        with self.assertRaises(AiError):
            self.provider(envelope('```json\n{"ok": true}\n```')).complete_json("s", {})

    def test_rejects_nan_and_non_object(self):
        for content in ('{"confidence": NaN}', "[1, 2]", '"text"'):
            with self.subTest(content=content), self.assertRaises(AiError):
                self.provider(envelope(content)).complete_json("s", {})

    def test_bad_envelope(self):
        for body in ({"choices": []}, {"choices": [{"message": {"content": 7}}]}, b"not json"):
            with self.subTest(body=body), self.assertRaises(AiError):
                self.provider(body).complete_json("s", {})

    def test_strict_json(self):
        self.assertEqual(strict_json(b'{"a": 1}', "x"), {"a": 1})
        with self.assertRaises(AiError):
            strict_json("Infinity", "x")

    def test_base_url_without_scheme_is_an_ai_error(self):
        provider = OpenAICompatProvider(AiSettings(base_url="api.deepseek.com", api_key="k", model="m"))
        with self.assertRaises(AiError):
            provider.complete_json("s", {})

    def test_truncated_body_is_an_ai_error(self):
        import http.client

        class Truncated(FakeResponse):
            def read(self):
                raise http.client.IncompleteRead(b"{")

        provider = OpenAICompatProvider(self.settings, opener=lambda request, timeout: Truncated(b""))
        with self.assertRaises(AiError):
            provider.complete_json("s", {})


if __name__ == "__main__":
    unittest.main()
