import json
from pathlib import Path
import tempfile
import unittest

from shutong.store.db import Database
from shutong.store.settings import DEFAULTS, SettingsStore


class SettingsStoreTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        db = Database(Path(self._directory.name) / "shutong.db")
        db.migrate()
        self.settings = SettingsStore(db)

    def test_round_trip_and_defaults(self):
        self.assertEqual(self.settings.get("ai.threshold"), 0.85)
        self.assertEqual(self.settings.get("unknown.key", "x"), "x")
        self.settings.set("ai.threshold", 0.9)
        self.settings.set("ai.model", "deepseek-chat")
        self.assertEqual((self.settings.get("ai.threshold"), self.settings.get("ai.model")), (0.9, "deepseek-chat"))
        self.settings.delete("ai.threshold")
        self.assertEqual(self.settings.get("ai.threshold"), DEFAULTS["ai.threshold"])

    def test_public_masks_secrets(self):
        self.assertEqual(self.settings.public()["bangumi.token"], "")
        self.settings.set("bangumi.token", "bgm-real-secret")
        self.settings.set("ai.api_key", "sk-real-secret")
        public = self.settings.public()
        self.assertEqual((public["bangumi.token"], public["ai.api_key"]), ("已设置", "已设置"))
        dumped = json.dumps(public, ensure_ascii=False)
        self.assertNotIn("bgm-real-secret", dumped)
        self.assertNotIn("sk-real-secret", dumped)
        self.assertNotIn("ai.daily_limit", public)
        self.assertEqual((public["network.proxy"], public["ai.use_proxy"]), ("", False))


if __name__ == "__main__":
    unittest.main()
