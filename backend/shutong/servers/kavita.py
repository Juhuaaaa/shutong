"""Kavita: the API client (login, scans, cover refreshes) and the MediaServer adapter over it."""
from __future__ import annotations

import json
import socket
from typing import Any, Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from shutong.servers.base import MediaServer, ServerError, ServerLibrary


class KavitaClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        opener: Callable[..., Any] = urlopen,
        timeout: float = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._opener = opener
        self._timeout = timeout
        self._token: Optional[str] = None

    def login(self) -> str:
        self._token = self._request(
            "POST",
            "/api/Account/login",
            {"username": self._username, "password": self._password},
            authenticated=False,
        )["token"]
        return self._token

    def libraries(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/api/Library/libraries")

    def scan_library(self, library_id: int, force: bool = False) -> None:
        self._request(
            "POST",
            "/api/Library/scan?libraryId={0}&force={1}".format(library_id, _flag(force)),
            {},
        )

    def refresh_library_covers(self, library_id: int) -> None:
        """Regenerate covers; a plain scan keeps the old cover images."""
        self._request(
            "POST",
            "/api/Library/refresh-metadata?libraryId={0}&force=true".format(library_id),
            {},
        )

    def search_series(self, name: str) -> List[Dict[str, Any]]:
        return self._request(
            "GET", "/api/Search/search?queryString={0}".format(quote(name))
        )["series"]

    def scan_series(self, library_id: int, series_id: int) -> None:
        self._request("POST", "/api/Series/scan", _series_body(library_id, series_id))

    def refresh_series_covers(self, library_id: int, series_id: int) -> None:
        self._request(
            "POST", "/api/Series/refresh-metadata", _series_body(library_id, series_id)
        )

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        authenticated: bool = True,
    ) -> Any:
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + (self._token or self.login())
        request = Request(
            self.base_url + path,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers=headers,
            method=method,
        )
        with self._opener(request, timeout=self._timeout) as response:
            payload = response.read()
        return json.loads(payload) if payload else None


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _series_body(library_id: int, series_id: int) -> Dict[str, Any]:
    return {"libraryId": library_id, "seriesId": series_id, "forceUpdate": True}


class KavitaServer:
    """``MediaServer`` for Kavita; every failure becomes a ``ServerError`` in Chinese."""

    def __init__(self, record, opener: Callable[..., Any] = urlopen) -> None:
        self.base_url = record.base_url.rstrip("/")
        self.client = KavitaClient(record.base_url, record.username, record.password, opener=opener, timeout=30)

    def test(self) -> None:
        self._call(self.client.login)

    def libraries(self) -> List[ServerLibrary]:
        return [ServerLibrary(int(entry["id"]), str(entry.get("name", ""))) for entry in self._call(self.client.libraries)]

    def scan_library(self, library_id: int) -> None:
        self._call(self.client.scan_library, library_id)

    def refresh_series(self, library_id: int, series_name: str) -> bool:
        for series in self._call(self.client.search_series, series_name) or []:
            names = {series.get("name"), series.get("localizedName"), series.get("originalName")}
            if series_name in names and series.get("libraryId") == library_id:
                self._call(self.client.refresh_series_covers, library_id, series["seriesId"])
                return True
        return False

    def _call(self, fn, *args):
        try:
            return fn(*args)
        except HTTPError as error:
            if error.code in (401, 403):
                raise ServerError("Kavita 用户名或密码错误") from None
            raise ServerError("Kavita 返回错误：{0}".format(error.code)) from None
        except (URLError, socket.timeout, ConnectionError, OSError):
            raise ServerError("连不上 Kavita：{0}".format(self.base_url)) from None
        except (ValueError, KeyError, TypeError):
            raise ServerError("Kavita 返回了无法识别的内容") from None


def server_for(record) -> MediaServer:
    if record.kind == "kavita":
        return KavitaServer(record)
    raise ServerError("不支持的媒体服务器：{0}".format(record.kind))
