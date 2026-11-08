import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from shutong import cli
from shutong.logs import shutdown_logging
from shutong.metadata.offline import OfflineSource


class ServeTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)

    def run_serve(self, *extra):
        captured = {}
        self.addCleanup(shutdown_logging, self.root / "data")  # Windows cannot delete an open log file

        def fake_run(app, host, port):
            captured.update(app=app, host=host, port=port)

        with mock.patch("uvicorn.run", fake_run):
            code = cli.main(["--data", str(self.root / "data"), "serve", "--port", "9999", *extra])
        return code, captured

    def test_finds_the_built_web_ui(self):
        dist = self.root / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html>书童</html>", encoding="utf-8")
        with mock.patch.dict("os.environ", {"SHUTONG_WEB": str(dist)}):
            code, captured = self.run_serve()
        self.assertEqual(code, 0)
        client = TestClient(captured["app"])
        self.assertIn("书童", client.get("/review").text)
        self.assertEqual(client.get("/api/libraries").status_code, 401)

    def test_the_page_is_never_served_stale(self):
        # An upgrade renames the bundles: a cached index.html would point at files that are gone.
        dist = self.root / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<html>书童</html>", encoding="utf-8")
        (dist / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
        with mock.patch.dict("os.environ", {"SHUTONG_WEB": str(dist)}):
            code, captured = self.run_serve()
        client = TestClient(captured["app"])
        for path in ("/", "/review", "/index.html"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).headers["cache-control"], "no-cache")
        self.assertIn("immutable", client.get("/assets/app-abc123.js").headers["cache-control"])
        # A bundle an old page asks for is a 404, not the page itself served as JavaScript.
        self.assertEqual(client.get("/assets/app-old999.js").status_code, 404)

    def test_default_web_dir_is_the_repo_build(self):
        self.assertEqual(cli.default_web_dir(), Path(cli.__file__).resolve().parents[2] / "web" / "dist")

    def test_offline_metadata_must_exist(self):
        code, captured = self.run_serve("--offline-metadata", str(self.root / "missing.json"))
        self.assertEqual((code, captured), (2, {}))

    def test_offline_metadata_answers_searches(self):
        path = self.root / "subjects.json"
        path.write_text(json.dumps([{"subject_id": 133315, "name": "ダンジョン飯", "name_cn": "迷宫饭", "total_volumes": 14}],
                                   ensure_ascii=False), encoding="utf-8")
        source = OfflineSource(path)
        self.assertEqual([subject.subject_id for subject in source.search("迷宫饭", "manga")], ["133315"])
        self.assertEqual(source.search("别的", "manga"), ())
        self.assertEqual(source.get(133315).name_cn, "迷宫饭")


if __name__ == "__main__":
    unittest.main()
