"""Tests for the Kavita API client."""
import json
import unittest

from shutong.servers.kavita import KavitaClient, KavitaServer


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
    def __init__(self):
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        if request.full_url.endswith("/api/Account/login"):
            return FakeResponse(json.dumps({"token": "t0k"}).encode())
        if "/api/Search/search" in request.full_url:
            return FakeResponse(json.dumps({"series": [{"seriesId": 9}]}).encode())
        return FakeResponse(b"")


class KavitaClientTests(unittest.TestCase):
    def setUp(self):
        self.opener = FakeOpener()
        self.client = KavitaClient("http://kavita:5000/", "user", "pw", opener=self.opener)

    def test_logs_in_once_and_sends_bearer_token(self):
        self.client.scan_library(3, force=True)
        self.client.refresh_library_covers(3)
        login, scan, refresh = self.opener.requests
        self.assertEqual(
            {"username": "user", "password": "pw"}, json.loads(login.data)
        )
        self.assertIsNone(login.get_header("Authorization"))
        self.assertEqual(
            "http://kavita:5000/api/Library/scan?libraryId=3&force=true", scan.full_url
        )
        self.assertEqual("Bearer t0k", scan.get_header("Authorization"))
        self.assertIn("refresh-metadata?libraryId=3&force=true", refresh.full_url)

    def test_series_calls(self):
        self.assertEqual([{"seriesId": 9}], self.client.search_series("怪怪守护神"))
        self.client.refresh_series_covers(3, 9)
        search, refresh = self.opener.requests[1:]
        self.assertIn("%E6%80%AA", search.full_url)
        self.assertEqual("GET", search.get_method())
        self.assertEqual(
            {"libraryId": 3, "seriesId": 9, "forceUpdate": True}, json.loads(refresh.data)
        )


class ScriptedOpener:
    """Answers by URL fragment; an exception instance is raised instead of answered."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        for fragment, answer in self.routes.items():
            if fragment in request.full_url:
                if isinstance(answer, BaseException):
                    raise answer
                return FakeResponse(json.dumps(answer).encode() if answer is not None else b"")
        return FakeResponse(b"")


def record(**overrides):
    from shutong.store.servers import ServerRecord

    values = dict(id=1, kind="kavita", name="家里", base_url="http://kavita:5000", username="user",
                  password="s3cret-pw", enabled=True)
    values.update(overrides)
    return ServerRecord(**values)


class KavitaServerTests(unittest.TestCase):
    def test_libraries_and_scan(self):
        opener = ScriptedOpener({"/api/Account/login": {"token": "t"},
                                 "/api/Library/libraries": [{"id": 3, "name": "漫画"}, {"id": 7, "name": "轻小说"}]})
        server = KavitaServer(record(), opener=opener)
        server.test()
        self.assertEqual([(entry.id, entry.name) for entry in server.libraries()], [("3", "漫画"), ("7", "轻小说")])
        server.scan_library(3)
        self.assertIn("/api/Library/scan?libraryId=3&force=false", opener.requests[-1].full_url)

    def test_errors_are_chinese_and_hide_the_password(self):
        from urllib.error import HTTPError, URLError

        from shutong.servers.base import ServerError

        cases = [
            (HTTPError("http://kavita:5000/api/Account/login", 401, "Unauthorized", {}, None), "用户名或密码错误"),
            (URLError("Connection refused"), "连不上 Kavita"),
            (HTTPError("http://kavita:5000/api/Account/login", 500, "boom", {}, None), "Kavita 返回错误：500"),
        ]
        for error, message in cases:
            with self.subTest(message=message):
                server = KavitaServer(record(), opener=ScriptedOpener({"/api/Account/login": error}))
                with self.assertRaises(ServerError) as caught:
                    server.test()
                self.assertIn(message, str(caught.exception))
                self.assertNotIn("s3cret-pw", str(caught.exception))

    def test_refresh_series_matches_name_and_library(self):
        opener = ScriptedOpener({"/api/Account/login": {"token": "t"}, "/api/Search/search": {"series": [
            {"seriesId": 1, "name": "迷宫饭 外传", "libraryId": 3},
            {"seriesId": 2, "name": "迷宫饭", "libraryId": 7},
            {"seriesId": 3, "name": "迷宫饭", "libraryId": 3},
        ]}})
        server = KavitaServer(record(), opener=opener)
        self.assertTrue(server.refresh_series(3, "迷宫饭"))
        self.assertEqual(json.loads(opener.requests[-1].data)["seriesId"], 3)
        self.assertFalse(server.refresh_series(3, "不存在"))


if __name__ == "__main__":
    unittest.main()
