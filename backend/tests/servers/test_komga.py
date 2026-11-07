"""Tests for the Komga media server adapter."""
import json
import unittest
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

from shutong.servers.base import ServerError, ServerLibrary
from shutong.servers.kavita import server_for
from shutong.servers.komga import KomgaServer


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, routes=None, error=None):
        self.requests, self.routes, self.error = [], routes or {}, error

    def __call__(self, request, timeout):
        self.requests.append(request)
        if self.error:
            raise self.error
        for prefix, payload in self.routes.items():
            if request.full_url.startswith("http://komga:25600" + prefix):
                return FakeResponse(json.dumps(payload).encode())
        return FakeResponse(b"")


def record(**overrides):
    values = dict(kind="komga", name="Komga", base_url="http://komga:25600/", username="me@x.cn", password="pw")
    values.update(overrides)
    return SimpleNamespace(**values)


def series(name, library="0LIB", series_id="0SER"):
    return {"id": series_id, "name": name, "libraryId": library, "metadata": {"title": name + " (2)"}}


class KomgaServerTests(unittest.TestCase):
    def test_test_uses_basic_auth_on_the_current_user(self):
        opener = FakeOpener({"/api/v2/users/me": {"id": "u"}})
        KomgaServer(record(), opener=opener).test()
        request = opener.requests[0]
        self.assertEqual(request.full_url, "http://komga:25600/api/v2/users/me")
        self.assertEqual(request.get_header("Authorization"), "Basic bWVAeC5jbjpwdw==")

    def test_libraries_keep_text_ids(self):
        opener = FakeOpener({"/api/v1/libraries": [{"id": "0S5E73NR0E2MP", "name": "漫画", "root": "/data"}]})
        self.assertEqual(KomgaServer(record(), opener=opener).libraries(), [ServerLibrary("0S5E73NR0E2MP", "漫画")])

    def test_scan_library(self):
        opener = FakeOpener()
        KomgaServer(record(), opener=opener).scan_library("0LIB")
        request = opener.requests[0]
        self.assertEqual((request.get_method(), request.full_url), ("POST", "http://komga:25600/api/v1/libraries/0LIB/scan"))

    def test_refresh_series_matches_the_folder_name_in_that_library(self):
        opener = FakeOpener({"/api/v1/series?": {"content": [series("怪怪守护神 外传", series_id="0X"),
                                                              series("怪怪守护神", library="0OTHER", series_id="0Y"),
                                                              series("怪怪守护神", series_id="0Z")]}})
        self.assertTrue(KomgaServer(record(), opener=opener).refresh_series("0LIB", "怪怪守护神"))
        search, refresh = opener.requests
        self.assertIn("library_id=0LIB", search.full_url)
        self.assertIn("search=%E6%80%AA", search.full_url)
        self.assertEqual((refresh.get_method(), refresh.full_url),
                         ("POST", "http://komga:25600/api/v1/series/0Z/metadata/refresh"))

    def test_refresh_series_without_a_match_does_nothing(self):
        opener = FakeOpener({"/api/v1/series?": {"content": [series("别的")]}})
        self.assertFalse(KomgaServer(record(), opener=opener).refresh_series("0LIB", "怪怪守护神"))
        self.assertEqual(len(opener.requests), 1)

    def test_errors_name_komga_and_hide_the_password(self):
        cases = [(HTTPError("u", 401, "x", {}, BytesIO()), "Komga 用户名或密码错误"),
                 (HTTPError("u", 500, "x", {}, BytesIO()), "Komga 返回错误：500"),
                 (URLError("refused"), "连不上 Komga：http://komga:25600")]
        for error, message in cases:
            with self.assertRaises(ServerError) as caught:
                KomgaServer(record(), opener=FakeOpener(error=error)).test()
            self.assertEqual(str(caught.exception), message)
            self.assertNotIn("pw", str(caught.exception))

    def test_server_for_picks_komga(self):
        self.assertIsInstance(server_for(record()), KomgaServer)


if __name__ == "__main__":
    unittest.main()
