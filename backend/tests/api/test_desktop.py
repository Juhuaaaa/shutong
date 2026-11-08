"""Desktop mode: no login, a random token in a cookie, and nothing but the app's own window gets in."""
from shutong import __version__
from pathlib import Path
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from shutong.api.app import create_app
from shutong.api.auth import COOKIE
from shutong.logs import shutdown_logging

from .helpers import ApiCase

TOKEN = "t" * 64
ORIGIN = "http://127.0.0.1:8123"


class DesktopCase(ApiCase):
    def setUp(self):
        super().setUp()
        self.desktop_data = self.root / "desktop-data"
        self.desktop = create_app(self.desktop_data, inline_jobs=True, services_factory=self.services,
                                  desktop_token=TOKEN)
        self.window = TestClient(self.desktop, base_url=ORIGIN, cookies={COOKIE: TOKEN})
        self.addCleanup(self.window.close)
        self.addCleanup(self.desktop.state.jobs.stop)
        self.addCleanup(shutdown_logging, self.desktop_data)

    def library(self, **overrides):
        self.root.joinpath("库").mkdir(exist_ok=True)
        body = {"name": "漫画", "kind": "manga", "source_dir": "", "library_dir": str(self.root / "库"),
                "source_policy": "keep"}
        body.update(overrides)
        response = self.window.post("/api/libraries", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class AuthTests(DesktopCase):
    def test_token_cookie_is_logged_in(self):
        self.assertEqual(self.window.get("/api/auth/status").json(),
                         {"configured": True, "logged_in": True, "desktop": True, "version": __version__})
        self.assertEqual(self.window.get("/api/libraries").status_code, 200)

    def test_wrong_or_missing_token_is_refused(self):
        for cookies in ({COOKIE: "wrong"}, {}):
            with TestClient(self.desktop, base_url=ORIGIN, cookies=cookies) as client:
                self.assertEqual(client.get("/api/libraries").status_code, 401)
                self.assertFalse(client.get("/api/auth/status").json()["logged_in"])

    def test_password_endpoints_do_not_exist(self):
        for path, body in (("setup", {"password": "12345678"}), ("login", {"password": "12345678"}),
                           ("password", {"old": "12345678", "new": "87654321"})):
            self.assertEqual(self.window.post("/api/auth/" + path, json=body).status_code, 404, path)
        self.assertEqual(self.window.post("/api/auth/logout").status_code, 404)

    def test_web_mode_says_it_is_not_desktop(self):
        self.assertFalse(self.client.get("/api/auth/status").json()["desktop"])


class GuardTests(DesktopCase):
    def test_other_host_is_refused(self):
        response = self.window.get("/api/libraries", headers={"Host": "evil.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.window.get("/api/libraries", headers={"Host": "127.0.0.1.evil.example:8123"}).status_code, 403)

    def test_other_origin_is_refused(self):
        for origin in ("http://127.0.0.1:9999", "https://evil.example", "null"):
            self.assertEqual(self.window.get("/api/libraries", headers={"Origin": origin}).status_code, 403, origin)

    def test_own_origin_is_fine(self):
        self.assertEqual(self.window.post("/api/libraries/1/scan-paths", json={"paths": ["/x"]},
                                          headers={"Origin": ORIGIN}).status_code in (404, 409), True)
        self.assertEqual(self.window.get("/api/libraries", headers={"Origin": ORIGIN}).status_code, 200)

    def test_websocket_from_another_origin_is_refused(self):
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.window.websocket_connect("/api/ws", headers={"Host": "127.0.0.1:8123", "Origin": "https://evil.example"}):
                pass
        self.assertEqual(caught.exception.code, 4403)

    def test_websocket_from_the_window_connects(self):
        with self.window.websocket_connect("/api/ws", headers={"Host": "127.0.0.1:8123", "Origin": ORIGIN}):
            pass

    def test_web_mode_has_no_guard(self):
        self.assertEqual(self.client.get("/api/auth/status", headers={"Host": "nas.example:8899"}).status_code, 200)


class LibraryTests(DesktopCase):
    def test_library_without_source_can_keep_originals(self):
        self.assertEqual(self.library()["source_policy"], "keep")

    def test_web_mode_still_cannot(self):
        self.login()
        response = self.client.post("/api/libraries", json={"name": "漫画", "kind": "manga", "source_dir": "",
                                                            "library_dir": str(self.root)})
        self.assertEqual(response.status_code, 422)

    def _create(self, library_dir):
        return self.window.post("/api/libraries", json={"name": "漫画", "kind": "manga", "source_dir": "",
                                                        "library_dir": library_dir, "source_policy": "keep"})

    def test_library_dir_must_be_absolute(self):
        self.assertEqual(self._create("漫画").status_code, 422)
        self.assertFalse(Path("漫画").exists())

    def test_library_dir_that_cannot_be_created_is_explained(self):
        blocker = self.root / "一个文件"
        blocker.write_text("x")
        response = self._create(str(blocker / "漫画"))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("漫画", response.json()["detail"])

    def test_missing_library_dir_is_created(self):
        target = self.root / "文档" / "书童库" / "漫画"
        self.assertTrue(self.library(library_dir=str(target))["available"])
        self.assertTrue(target.is_dir())


class ScanPathsTests(DesktopCase):
    def scan(self, library, *paths, client=None):
        return (client or self.window).post("/api/libraries/{0}/scan-paths".format(library["id"]),
                                            json={"paths": [str(path) for path in paths]})

    def test_web_mode_cannot_read_arbitrary_paths(self):
        self.login()
        library = self.make_library()
        self.assertEqual(self.scan(library, self.root, client=self.client).status_code, 404)

    def test_login_is_still_required(self):
        library = self.library()
        with TestClient(self.desktop, base_url=ORIGIN) as client:
            self.assertEqual(self.scan(library, self.root, client=client).status_code, 401)

    def test_no_ai_is_refused(self):
        library = self.library()
        self.ai = None
        self.assertEqual(self.scan(library, self.root / "x").status_code, 409)

    def test_relative_path_is_refused(self):
        self.assertEqual(self.scan(self.library(), "a/b").status_code, 422)
        self.assertEqual(self.scan(self.library(name="二"), *[]).status_code, 422)

    def test_drop_organizes_and_keeps_the_original(self):
        library = self.library()
        source = self.zip("迷宫饭/迷宫饭 Vol.01.zip", base=self.root / "下载")
        (self.root / "下载" / "说明.txt").write_text("x")
        response = self.scan(library, source.parent, self.root / "下载" / "说明.txt", self.root / "库")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["skipped"], [{"path": str(self.root / "下载" / "说明.txt"), "reason": "unsupported"}])
        self.assertEqual(body["rejected"], [str(self.root / "库")])
        job = self.window.get("/api/jobs/{0}".format(body["job_id"])).json()
        self.assertEqual(job["state"], "done", job)
        self.assertTrue(source.exists())
        self.assertTrue((self.root / "库" / "迷宫饭" / "迷宫饭 Vol.01.cbz").exists())

    def test_nothing_to_do_starts_no_job(self):
        body = self.scan(self.library(), self.root / "没有").json()
        self.assertIsNone(body["job_id"])
        self.assertEqual(body["skipped"][0]["reason"], "missing")
