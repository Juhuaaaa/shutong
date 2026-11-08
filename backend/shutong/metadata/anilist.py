"""AniList manga and light-novel entries over its public GraphQL API.

Searches work with Japanese, romanized or English titles only (not Chinese ones), and summaries are in
English. Results are cached in metadata_cache under ``anilist:`` keys.
"""
from __future__ import annotations

import html
import http.client
import json
import logging
import re
import socket
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from shutong.store.cache import CacheStore

from .bangumi import USER_AGENT, _is_transient_socket_error, _load_json
from .base import MetadataUnavailable, Subject

log = logging.getLogger("shutong.anilist")
ENDPOINT = "https://graphql.anilist.co"
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
_RETRY_DELAYS = (1, 2, 4)
_MAX_ATTEMPTS = 3
_DOWN_SECONDS = 300
_SEARCH_CACHE_TTL_SECONDS = 24 * 60 * 60
_SUBJECT_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
_WRITER_ROLES = ("Story", "Original Creator", "Original Story")  # "Story & Art" starts with "Story"
_ILLUSTRATOR_ROLES = ("Illustration",)

_FIELDS = """
  id title { romaji english native } synonyms description(asHtml: false)
  startDate { year month day } status volumes genres format coverImage { large }
  staff(perPage: 25) { edges { role node { name { full native } } } }
"""
_SEARCH = ("query ($search: String, $formats: [MediaFormat]) { Page(perPage: 10) { "
           "media(search: $search, type: MANGA, format_in: $formats) {" + _FIELDS + "} } }")
_GET = "query ($id: Int) { Media(id: $id, type: MANGA) {" + _FIELDS + "} }"


class AniListSource:
    name = "anilist"
    label = "AniList"

    def __init__(
        self,
        cache: CacheStore,
        opener: Callable[..., Any] = urlopen,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cache = cache
        self._opener = opener
        self._sleep = sleep
        self._clock = clock
        self._down_until = 0.0

    def search(self, query: str, kind: str) -> Tuple[Subject, ...]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("search title must be a non-empty string")
        text = query.strip()
        formats = ["NOVEL"] if kind == "novel" else ["MANGA", "ONE_SHOT"]
        cache_key = "anilist:search:{0}:{1}".format("novel" if kind == "novel" else "manga", text)
        response = self.cache.get(cache_key)
        if response is None:
            response = self._request({"query": _SEARCH, "variables": {"search": text, "formats": formats}})
            subjects = _search_subjects(response)
            self.cache.put(cache_key, response, ttl_seconds=_SEARCH_CACHE_TTL_SECONDS)
            return subjects
        return _search_subjects(response)

    def get(self, subject_id, *, fresh: bool = False) -> Subject:
        """``KeyError`` when AniList has no such entry; ``fresh`` skips the cache."""
        text = str(subject_id).strip()
        if isinstance(subject_id, bool) or not text.isdigit() or int(text) <= 0:
            raise KeyError(subject_id)
        cache_key = "anilist:subject:{0}".format(int(text))
        response = None if fresh else self.cache.get(cache_key)
        if response is None:
            try:
                response = self._request({"query": _GET, "variables": {"id": int(text)}})
            except HTTPError as error:
                if error.code == 404:
                    raise KeyError(subject_id) from error
                raise
            media = _media(response)
            if media is None:
                raise KeyError(subject_id)
            self.cache.put(cache_key, response, ttl_seconds=_SUBJECT_CACHE_TTL_SECONDS)
        media = _media(response)
        if media is None:
            raise KeyError(subject_id)
        return normalize_media(media)

    def _request(self, payload: Dict[str, Any]) -> Any:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(ENDPOINT, data=body, method="POST", headers={
            "Accept": "application/json", "Content-Type": "application/json", "User-Agent": USER_AGENT})
        if self._clock() < self._down_until:
            raise MetadataUnavailable("AniList 暂时无法访问（刚连不上过，稍后自动再试）")
        for attempt in range(_MAX_ATTEMPTS):
            delay = _RETRY_DELAYS[attempt]
            try:
                with self._opener(request, timeout=60) as response:
                    return _load_json(response.read(), "AniList")
            except HTTPError as error:
                if error.code not in _RETRYABLE_HTTP_CODES:
                    raise
                delay = _retry_after(error) or delay
                retryable_error = error
            except (socket.timeout, TimeoutError, ConnectionError, http.client.HTTPException) as error:
                retryable_error = error
            except URLError as error:
                if not isinstance(error.reason, OSError) or not _is_transient_socket_error(error.reason):
                    raise
                retryable_error = error
            except OSError as error:
                if not _is_transient_socket_error(error):
                    raise
                retryable_error = error
            log.warning("AniList 请求失败（第 %d/%d 次）：%s", attempt + 1, _MAX_ATTEMPTS, retryable_error)
            if attempt + 1 >= _MAX_ATTEMPTS:
                self._down_until = self._clock() + _DOWN_SECONDS
                raise MetadataUnavailable(
                    "AniList 暂时无法访问（试了 {0} 次）：{1}".format(_MAX_ATTEMPTS, retryable_error)
                ) from retryable_error
            self._sleep(delay)
        raise RuntimeError("unreachable AniList retry state")


def _retry_after(error: HTTPError) -> Optional[int]:
    value = (error.headers or {}).get("Retry-After") if error.headers is not None else None
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return min(max(seconds, 1), 60)


def _media(response: Any) -> Optional[dict]:
    data = response.get("data") if isinstance(response, dict) else None
    media = data.get("Media") if isinstance(data, dict) else None
    return media if isinstance(media, dict) else None


def _search_subjects(response: Any) -> Tuple[Subject, ...]:
    data = response.get("data") if isinstance(response, dict) else None
    found = data.get("Page") if isinstance(data, dict) else None
    media = found.get("media") if isinstance(found, dict) else None
    if not isinstance(media, list):
        raise ValueError("AniList search response must contain a media list")
    return tuple(normalize_media(entry) for entry in media if isinstance(entry, dict))


def normalize_media(media: dict) -> Subject:
    subject_id = media.get("id")
    if isinstance(subject_id, bool) or not isinstance(subject_id, int) or subject_id <= 0:
        raise ValueError("AniList media id must be a positive integer")
    title = media.get("title") if isinstance(media.get("title"), dict) else {}
    native, romaji, english = _text(title.get("native")), _text(title.get("romaji")), _text(title.get("english"))
    name = native or romaji or english
    synonyms = media.get("synonyms") if isinstance(media.get("synonyms"), list) else []
    aliases = [alias for alias in dict.fromkeys([english, romaji] + [_text(s) for s in synonyms])
               if alias and alias != name]
    status = media.get("status")
    volumes = media.get("volumes")
    media_format = media.get("format")
    cover = media.get("coverImage") if isinstance(media.get("coverImage"), dict) else {}
    genres = media.get("genres") if isinstance(media.get("genres"), list) else []
    return Subject(
        subject_id=str(subject_id),
        name=name,
        name_cn="",
        summary=_plain(media.get("description")),
        release_date=_date(media.get("startDate")),
        writers=_staff(media.get("staff"), _WRITER_ROLES),
        illustrators=_staff(media.get("staff"), _ILLUSTRATOR_ROLES),
        publisher="",
        genres=tuple(genre for genre in (_text(g) for g in genres) if genre),
        completed=status == "FINISHED",
        total_volumes=volumes if isinstance(volumes, int) and not isinstance(volumes, bool) and volumes > 0 else None,
        platform="小说" if media_format == "NOVEL" else "漫画",
        source="anilist",
        series=media_format != "ONE_SHOT",
        aliases=tuple(aliases),
        image=_text(cover.get("large")),
    )


def _staff(staff: Any, roles: Tuple[str, ...]) -> Tuple[str, ...]:
    edges = staff.get("edges") if isinstance(staff, dict) else None
    names: List[str] = []
    for edge in edges if isinstance(edges, list) else []:
        if not isinstance(edge, dict) or not _text(edge.get("role")).startswith(roles):
            continue
        node = edge.get("node") if isinstance(edge.get("node"), dict) else {}
        person = node.get("name") if isinstance(node.get("name"), dict) else {}
        name = _text(person.get("native")) or _text(person.get("full"))
        if name and name not in names:
            names.append(name)
    return tuple(names)


def _date(value: Any) -> Optional[str]:
    if not isinstance(value, dict) or not isinstance(value.get("year"), int):
        return None
    parts = ["{0:04d}".format(value["year"])]
    for key in ("month", "day"):
        if not isinstance(value.get(key), int):
            break
        parts.append("{0:02d}".format(value[key]))
    return "-".join(parts)


_SOURCE_NOTE = re.compile(r"\s*\((?:Source|source):[^)]*\)\s*$")
_BREAK = re.compile(r"<br\s*/?>\s*", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def _plain(value: Any) -> str:
    """AniList descriptions carry a little HTML and often end with a ``(Source: …)`` credit."""
    text = _text(value)
    text = _BREAK.sub("\n", text)
    text = html.unescape(_TAG.sub("", text))
    text = _SOURCE_NOTE.sub("", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
