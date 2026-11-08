import time
import unittest

from shutong import __version__
from unittest import mock

from .helpers import PASSWORD, ApiCase


class AuthTests(ApiCase):
    def test_first_status_is_unconfigured(self):
        self.assertEqual(self.client.get("/api/auth/status").json(), {"configured": False, "logged_in": False, "desktop": False, "version": __version__})

    def test_setup_logs_in_and_only_works_once(self):
        self.login()
        self.assertEqual(self.client.get("/api/auth/status").json(), {"configured": True, "logged_in": True, "desktop": False, "version": __version__})
        again = self.client.post("/api/auth/setup", json={"password": "another password"})
        self.assertEqual((again.status_code, again.json()["detail"]), (409, "密码已设置"))

    def test_short_password_rejected(self):
        response = self.client.post("/api/auth/setup", json={"password": "short"})
        self.assertEqual((response.status_code, response.json()["detail"]), (422, "密码至少 8 位"))

    def test_wrong_password_and_logout(self):
        self.login()
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/libraries").status_code, 401)
        self.assertEqual(self.client.get("/api/libraries").json(), {"detail": "未登录"})
        wrong = self.client.post("/api/auth/login", json={"password": "nope nope"})
        self.assertEqual((wrong.status_code, wrong.json()["detail"]), (401, "密码错误"))
        self.assertEqual(self.client.post("/api/auth/login", json={"password": PASSWORD}).status_code, 200)
        self.assertEqual(self.client.get("/api/libraries").status_code, 200)

    def test_tampered_cookie_rejected(self):
        self.login()
        expiry, signature = self.client.cookies["shutong_session"].split(".")
        self.client.cookies.clear()
        self.client.cookies.set("shutong_session", "{0}.{1}".format(int(expiry) + 999, signature))
        self.assertEqual(self.client.get("/api/libraries").status_code, 401)

    def test_expired_session_rejected(self):
        self.login()
        with mock.patch("shutong.api.auth.time.time", return_value=time.time() + 31 * 86400):
            self.assertEqual(self.client.get("/api/libraries").status_code, 401)

    def test_openapi_is_public(self):
        self.assertEqual(self.client.get("/api/openapi.json").status_code, 200)

    def test_change_password(self):
        self.login()
        bad = self.client.post("/api/auth/password", json={"old": "wrong one", "new": "new password"})
        self.assertEqual(bad.status_code, 401)
        ok = self.client.post("/api/auth/password", json={"old": PASSWORD, "new": "new password"})
        self.assertEqual(ok.status_code, 200)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.post("/api/auth/login", json={"password": PASSWORD}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"password": "new password"}).status_code, 200)

    def test_password_hash_is_not_in_settings_store_plaintext(self):
        self.login()
        from shutong.store.settings import SettingsStore

        stored = SettingsStore(self.app.state.db).get("auth.password_hash")
        self.assertTrue(stored.startswith("scrypt$"))
        self.assertNotIn(PASSWORD, stored)


if __name__ == "__main__":
    unittest.main()
