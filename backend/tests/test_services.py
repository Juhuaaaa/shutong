from pathlib import Path
import tempfile
import unittest
from urllib.request import urlopen

from shutong.ai.audit import AuditedAi
from shutong.metadata.bangumi import BangumiSource
from shutong.services import build_services
from shutong.store.db import Database
from shutong.store.settings import SettingsStore


class ServicesTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.db = Database(Path(self._directory.name) / "shutong.db")
        self.db.migrate()
        self.settings = SettingsStore(self.db)

    def test_build_services_without_ai(self):
        services = build_services(self.db)
        self.assertIsInstance(services.sources.primary, BangumiSource)
        self.assertIsNone(services.ai)
        self.assertEqual(services.config.ai_threshold, 0.85)

    def test_metadata_sources_follow_the_setting(self):
        self.assertEqual([source.name for source in build_services(self.db).sources.enabled], ["bangumi"])
        self.settings.set("metadata.sources", ["anilist", "bangumi"])
        services = build_services(self.db)
        self.assertEqual([source.name for source in services.sources.enabled], ["anilist", "bangumi"])
        self.settings.set("network.proxy", "http://192.168.1.2:7890")
        services = build_services(self.db)
        self.assertIs(services.sources.get("anilist")._opener, services.sources.get("bangumi")._opener)

    def test_build_services_with_ai_requires_all_fields(self):
        self.settings.set("ai.base_url", "https://api.deepseek.com/v1")
        self.settings.set("ai.api_key", "sk-x")
        self.assertIsNone(build_services(self.db).ai)  # model missing
        self.settings.set("ai.model", "deepseek-chat")
        services = build_services(self.db)
        self.assertIsInstance(services.ai, AuditedAi)
        self.assertEqual(services.ai.provider.settings.timeout, 180)

    def _enable_ai(self):
        for key, value in (("ai.base_url", "https://api.deepseek.com/v1"),
                           ("ai.api_key", "sk-x"), ("ai.model", "deepseek-chat")):
            self.settings.set(key, value)

    def test_proxy_is_for_bangumi_and_ai_only_when_switched_on(self):
        self._enable_ai()
        self.assertIs(build_services(self.db).sources.primary._opener, urlopen)
        self.settings.set("network.proxy", "http://192.168.1.2:7890")
        services = build_services(self.db)
        self.assertIsNot(services.sources.primary._opener, urlopen)
        self.assertIs(services.ai.provider._opener, urlopen)
        self.settings.set("ai.use_proxy", True)
        services = build_services(self.db)
        self.assertIs(services.ai.provider._opener.__self__, services.sources.primary._opener.__self__)

    def test_explicit_opener_wins(self):
        self._enable_ai()
        self.settings.set("network.proxy", "http://192.168.1.2:7890")
        opener = lambda request, timeout: None  # noqa: E731
        services = build_services(self.db, opener=opener)
        self.assertIs(services.sources.primary._opener, opener)
        self.assertIs(services.ai.provider._opener, opener)

    def test_bangumi_settings_are_used(self):
        self.settings.set("bangumi.token", "bgm-token")
        source = build_services(self.db).sources.primary
        self.assertEqual(source.settings.token, "bgm-token")

    def test_bangumi_mirror_for_api_and_images(self):
        source = build_services(self.db).sources.primary
        self.assertEqual(source.settings.image_base_url, "https://api.bgm.tv")
        # A mirror of the API usually serves its image endpoint too: images follow it unless set apart.
        self.settings.set("bangumi.base_url", "https://bgm.mirror.example/")
        self.assertEqual(build_services(self.db).sources.primary.settings.image_base_url, "https://bgm.mirror.example")
        self.settings.set("bangumi.image_base_url", "https://img.mirror.example")
        self.assertEqual(build_services(self.db).sources.primary.settings.image_base_url, "https://img.mirror.example")


if __name__ == "__main__":
    unittest.main()
