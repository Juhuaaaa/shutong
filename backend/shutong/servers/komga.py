"""Komga: the MediaServer adapter. Komga reads the metadata Shutong writes into the files, so a scan is enough;
a replaced file gets a new cover on that scan too. Library and series ids are text."""
from __future__ import annotations

import base64
import json
import socket
from typing import Any, Callable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from shutong.servers.base import ServerError, ServerLibrary


class KomgaServer:
    def __init__(self, record, opener: Callable[..., Any] = urlopen, timeout: float = 30) -> None:
        self.base_url = record.base_url.rstrip("/")
        token = base64.b64encode("{0}:{1}".format(record.username, record.password).encode("utf-8")).decode("ascii")
        self._authorization = "Basic " + token
        self._opener = opener
        self._timeout = timeout

    def test(self) -> None:
        self._request("GET", "/api/v2/users/me")

    def libraries(self) -> List[ServerLibrary]:
        return [ServerLibrary(str(entry["id"]), str(entry.get("name", ""))) for entry in self._request("GET", "/api/v1/libraries")]

    def scan_library(self, library_id: str) -> None:
        self._request("POST", "/api/v1/libraries/{0}/scan".format(quote(str(library_id), safe="")))

    def refresh_series(self, library_id: str, series_name: str) -> bool:
        """Re-read the metadata of the series whose folder is ``series_name``; Komga keeps the folder as its name."""
        page = self._request("GET", "/api/v1/series?library_id={0}&search={1}&size=50".format(
            quote(str(library_id), safe=""), quote(series_name, safe="")))
        for series in (page or {}).get("content", []):
            if series.get("name") == series_name and str(series.get("libraryId")) == str(library_id):
                self._request("POST", "/api/v1/series/{0}/metadata/refresh".format(quote(str(series["id"]), safe="")))
                return True
        return False

    def _request(self, method: str, path: str) -> Optional[Any]:
        request = Request(self.base_url + path, data=b"" if method == "POST" else None, method=method,
                          headers={"Authorization": self._authorization, "Accept": "application/json"})
        try:
            with self._opener(request, timeout=self._timeout) as response:
                payload = response.read()
            return json.loads(payload) if payload else None
        except HTTPError as error:
            if error.code in (401, 403):
                raise ServerError("Komga 用户名或密码错误") from None
            raise ServerError("Komga 返回错误：{0}".format(error.code)) from None
        except (URLError, socket.timeout, ConnectionError, OSError):
            raise ServerError("连不上 Komga：{0}".format(self.base_url)) from None
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ServerError("Komga 返回了无法识别的内容") from None
