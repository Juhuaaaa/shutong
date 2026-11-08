import unittest
from unittest import mock

from shutong.store.settings import SettingsStore

from .helpers import ApiCase


class SettingsRoutesTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_secrets_and_auth_are_hidden(self):
        SettingsStore(self.app.state.db).set("ai.api_key", "sk-secret")
        settings = self.client.get("/api/settings").json()
        self.assertEqual(settings["ai.api_key"], "已设置")
        self.assertFalse(any(key.startswith("auth.") for key in settings))
        self.assertNotIn("sk-secret", self.client.get("/api/settings").text)

    def test_patch_validates_keys_and_types(self):
        ok = self.client.patch("/api/settings", json={"ai.threshold": 0.9, "ai.use_proxy": True,
                                                      "ai.api_key": "sk-new"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["ai.threshold"], 0.9)
        self.assertEqual(SettingsStore(self.app.state.db).get("ai.api_key"), "sk-new")
        self.assertEqual(self.client.patch("/api/settings", json={"ai.threshold": "high"}).status_code, 422)
        self.assertEqual(self.client.patch("/api/settings", json={"ai.use_proxy": "yes"}).status_code, 422)
        self.assertEqual(self.client.patch("/api/settings", json={"ai.daily_limit": 10}).status_code, 422)
        self.assertNotIn("ai.daily_limit", self.client.get("/api/settings").json())
        for gone in ("ai.enabled", "ai.auto_adopt", "organize.auto_execute", "trash.retention_days"):
            self.assertEqual(self.client.patch("/api/settings", json={gone: True}).status_code, 422, gone)
        unknown = self.client.patch("/api/settings", json={"nope": 1})
        self.assertEqual((unknown.status_code, unknown.json()["detail"]), (422, "未知设置：nope"))
        self.assertEqual(self.client.patch("/api/settings", json={"auth.password_hash": "x"}).status_code, 422)

    def test_patch_checks_ranges(self):
        for body in ({"ai.threshold": 1.5}, {"ai.threshold": -0.1}):
            with self.subTest(body=body):
                self.assertEqual(self.client.patch("/api/settings", json=body).status_code, 422)

    def test_metadata_sources_are_validated(self):
        for bad in ([], ["bangumi", "bangumi"], ["douban"], "bangumi", [1]):
            with self.subTest(bad=bad):
                self.assertEqual(self.client.patch("/api/settings", json={"metadata.sources": bad}).status_code, 422)
        self.assertEqual(self.client.get("/api/settings").json()["metadata.sources"], ["bangumi"])
        ok = self.client.patch("/api/settings", json={"metadata.sources": ["anilist", "bangumi"]})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.client.get("/api/settings").json()["metadata.sources"], ["anilist", "bangumi"])

    def test_bangumi_addresses_are_web_addresses(self):
        for key in ("bangumi.base_url", "bangumi.image_base_url"):
            for bad in ("bgm.mirror.example", "ftp://x", "https://"):
                with self.subTest(key=key, bad=bad):
                    self.assertEqual(self.client.patch("/api/settings", json={key: bad}).status_code, 422)
        ok = self.client.patch("/api/settings", json={"bangumi.image_base_url": "https://img.mirror.example/",
                                                       "bangumi.base_url": "http://192.168.1.2:8080"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.client.patch("/api/settings", json={"bangumi.image_base_url": ""}).status_code, 200)

    def test_proxy_is_validated(self):
        bad = self.client.patch("/api/settings", json={"network.proxy": "192.168.1.2:7890"})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("代理地址格式不对", bad.json()["detail"])
        ok = self.client.patch("/api/settings", json={"network.proxy": "socks5h://192.168.1.2:7891", "ai.use_proxy": True})
        self.assertEqual((ok.status_code, ok.json()["network.proxy"], ok.json()["ai.use_proxy"]),
                         (200, "socks5h://192.168.1.2:7891", True))
        self.assertEqual(self.client.patch("/api/settings", json={"network.proxy": ""}).status_code, 200)

    def test_proxy_test(self):
        seen = []

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b"{}"

        def factory(proxy):
            seen.append(proxy)
            return lambda request, timeout: (seen.append((request.full_url, timeout)), Response())[1]

        with mock.patch("shutong.api.routes.settings.make_opener", side_effect=factory):
            result = self.client.post("/api/settings/proxy-test", json={"proxy": "http://192.168.1.2:7890"}).json()
        self.assertEqual((result["ok"], result["error"]), (True, None))
        self.assertIsInstance(result["elapsed_ms"], int)
        self.assertEqual(seen[0].host, "192.168.1.2")
        self.assertEqual(seen[1], ("https://api.bgm.tv/v0/subjects/1", 15))

        def timeout(proxy):
            def opener(request, timeout):
                raise TimeoutError("timed out")
            return opener

        with mock.patch("shutong.api.routes.settings.make_opener", side_effect=timeout):
            result = self.client.post("/api/settings/proxy-test", json={}).json()
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["error"])
        bad = self.client.post("/api/settings/proxy-test", json={"proxy": "nope"}).json()
        self.assertEqual(bad["ok"], False)
        self.assertIn("代理地址格式不对", bad["error"])

    def test_ai_test_without_configuration(self):
        self.assertEqual(self.client.post("/api/settings/ai-test").json()["ok"], False)


class DeletePolicyTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_delete_policy_removes_the_source_for_good(self):
        library = self.make_library(source_policy="delete")
        source = self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.client.post("/api/libraries/{0}/scan".format(library["id"]))
        [item] = self.client.get("/api/items", params={"library_id": library["id"]}).json()["items"]
        self.assertEqual(item["status"], "published")
        self.assertFalse(source.exists())
        self.assertFalse((self.root / "source" / ".shutong").exists())
        self.assertEqual(self.client.get("/api/trash").status_code, 404)

    def test_ai_calls_listing(self):
        self.assertEqual(self.client.get("/api/ai/calls").json(), [])


if __name__ == "__main__":
    unittest.main()
