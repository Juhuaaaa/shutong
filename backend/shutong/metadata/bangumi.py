"""Cached Bangumi book-subject API access and subject normalization.

Copied from the legacy shutong.core.common.bangumi; results are cached in metadata_cache.
"""
from __future__ import annotations

from dataclasses import dataclass
import errno
import http.client
import json
import logging
import math
import socket
import ssl
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from shutong.store.cache import CacheStore

from .base import MetadataUnavailable, Subject
from shutong.net import USER_AGENT  # noqa: F401  (also imported from here by other modules)

log = logging.getLogger("shutong.bangumi")
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
_RETRY_DELAYS = (1, 2, 4)
_MAX_ATTEMPTS = 3
_DOWN_SECONDS = 300  # after giving up, later requests fail at once for this long (the cache still answers)
DEFAULT_BASE_URL = "https://api.bgm.tv"
_IMAGE_PATH = "/v0/subjects/{0}/image?type={1}"


def image_url(base: str, subject_id, size: str = "common") -> str:
    """A subject's cover through the API's image endpoint, at ``base`` (the official site or a mirror)."""
    return (base or DEFAULT_BASE_URL).rstrip("/") + _IMAGE_PATH.format(subject_id, size)
_SEARCH_CACHE_TTL_SECONDS = 24 * 60 * 60
_SUBJECT_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class BangumiSettings:
    base_url: str = DEFAULT_BASE_URL
    token: Optional[str] = None
    image_base_url: str = ""  # a mirror of Bangumi's image host (lain.bgm.tv); empty: as the API names them


class BangumiSource:
    """Bangumi book subjects with responses cached in the metadata_cache table."""

    name = "bangumi"
    label = "Bangumi"

    def __init__(
        self,
        settings: BangumiSettings,
        cache: CacheStore,
        opener: Callable[..., Any] = urlopen,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.cache = cache
        self._clock = clock
        self._down_until = 0.0
        self._opener = opener
        self._sleep = sleep

    def search(self, query: str, kind: str) -> Tuple[Subject, ...]:
        """Book subjects for ``query``; ``kind`` filtering happens in metadata.rank."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("search title must be a non-empty string")
        normalized_title = query.strip()
        # Key format kept from the legacy organizer so its api_cache can be replayed.
        cache_key = "bangumi:search:manga:{0}".format(normalized_title)
        response = self.cache.get(cache_key)
        if response is None:
            response = self._request_json(
                "/v0/search/subjects?limit=8",
                payload={"keyword": normalized_title, "filter": {"type": [1]}},
            )
            subjects = _normalize_search_response(response, self.settings.image_base_url, self.settings.base_url)
            self.cache.put(
                cache_key, response, ttl_seconds=_SEARCH_CACHE_TTL_SECONDS
            )
            return subjects
        return _normalize_search_response(response, self.settings.image_base_url, self.settings.base_url)

    def get(self, subject_id, *, fresh: bool = False) -> Subject:
        """``fresh`` asks Bangumi again instead of answering from the cache (and updates the cache)."""
        text = str(subject_id).strip()
        if isinstance(subject_id, bool) or not text.isdigit() or int(text) <= 0:
            raise ValueError("subject id must be a positive integer")
        subject_id = int(text)
        cache_key = "bangumi:subject:{0}".format(subject_id)
        response = None if fresh else self.cache.get(cache_key)
        if response is None:
            response = self._request_json("/v0/subjects/{0}".format(subject_id))
            subject = normalize_subject(response, self.settings.image_base_url, self.settings.base_url)
            if subject.subject_id != str(subject_id):
                raise ValueError("Bangumi subject id does not match request")
            self.cache.put(
                cache_key, response, ttl_seconds=_SUBJECT_CACHE_TTL_SECONDS
            )
            return subject
        subject = normalize_subject(response, self.settings.image_base_url, self.settings.base_url)
        if subject.subject_id != str(subject_id):
            raise ValueError("Bangumi subject id does not match request")
        return subject

    def _request_json(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        body = None
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if payload is not None:
            body = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.settings.token:
            headers["Authorization"] = "Bearer {0}".format(
                self.settings.token
            )
        request = Request(
            self.settings.base_url.rstrip("/") + path,
            data=body,
            headers=headers,
            method="POST" if body is not None else "GET",
        )

        if self._clock() < self._down_until:
            raise MetadataUnavailable("Bangumi 暂时无法访问（刚连不上过，稍后自动再试）")
        for attempt in range(_MAX_ATTEMPTS):
            try:
                with self._opener(request, timeout=60) as response:
                    return _load_json(response.read(), "Bangumi")
            except HTTPError as error:
                if error.code not in _RETRYABLE_HTTP_CODES:
                    raise
                retryable_error = error
            except (socket.timeout, TimeoutError, ConnectionError, http.client.HTTPException) as error:
                # HTTPException covers truncated bodies (IncompleteRead) and dropped connections.
                retryable_error = error
            except URLError as error:
                if not isinstance(error.reason, OSError) or not _is_transient_socket_error(
                    error.reason
                ):
                    raise
                retryable_error = error
            except OSError as error:
                if not _is_transient_socket_error(error):
                    raise
                retryable_error = error
            log.warning("Bangumi 请求失败（第 %d/%d 次）：%s %s", attempt + 1, _MAX_ATTEMPTS, path, retryable_error)
            if attempt + 1 >= _MAX_ATTEMPTS:
                log.error("Bangumi 暂时无法访问，放弃：%s；之后 %d 秒内不再请求", path, _DOWN_SECONDS)
                self._down_until = self._clock() + _DOWN_SECONDS
                raise MetadataUnavailable(
                    "Bangumi 暂时无法访问（试了 {0} 次）：{1}".format(_MAX_ATTEMPTS, retryable_error)
                ) from retryable_error
            self._sleep(_RETRY_DELAYS[attempt])
        raise RuntimeError("unreachable Bangumi retry state")


IMAGE_HOSTS = ("https://lain.bgm.tv", "http://lain.bgm.tv")


def _cover(value: dict, subject_id: int, image_base: str, api_base: str) -> str:
    """The cover file Bangumi names, on a mirror of its image host when one is set; else the API's image endpoint."""
    images = value.get("images") if isinstance(value.get("images"), dict) else {}
    named = _text(images.get("common")) or _text(images.get("large"))
    if not named:
        return image_url(api_base, subject_id)
    if image_base:
        for host in IMAGE_HOSTS:
            if named.startswith(host + "/"):
                return image_base.rstrip("/") + named[len(host):]
    return named


def normalize_subject(value: Any, image_base: str = "", api_base: str = DEFAULT_BASE_URL) -> Subject:
    if not isinstance(value, dict):
        raise ValueError("Bangumi subject must be an object")
    subject_id = value.get("id")
    _require_positive_integer(subject_id, "subject id")
    infobox = value.get("infobox")
    entries = infobox if isinstance(infobox, list) else []
    writers = _infobox_values(entries, {"作者", "作画", "原作"})
    publishers = _infobox_values(entries, {"出版社", "连载杂志", "連載雜誌", "发行"})
    total_volumes = _positive_integer_or_none(value.get("volumes"))
    if total_volumes is None:
        total_volumes = _first_volume_count(entries)
    completed = value.get("completed") is True or _has_completed_status(entries)
    tags = value.get("tags")
    genres = []
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict):
                name = _text(tag.get("name"))
                if name and name not in genres:
                    genres.append(name)
    release_date = _text(value.get("date")) or None
    return Subject(
        subject_id=subject_id,
        name=_text(value.get("name")),
        name_cn=_text(value.get("name_cn")),
        summary=_text(value.get("summary")) or _text(value.get("short_summary")),
        release_date=release_date,
        writers=tuple(writers),
        publisher=", ".join(publishers),
        genres=tuple(genres),
        completed=completed,
        total_volumes=total_volumes,
        platform=_text(value.get("platform")),
        series=value.get("series") if isinstance(value.get("series"), bool) else None,
        image=_cover(value, subject_id, image_base, api_base),
    )


def _normalize_search_response(value: Any, image_base: str = "", api_base: str = DEFAULT_BASE_URL) -> Tuple[Subject, ...]:
    if not isinstance(value, dict) or not isinstance(value.get("data"), list):
        raise ValueError("Bangumi search response must contain a data list")
    return tuple(normalize_subject(item, image_base, api_base) for item in value["data"])


def _load_json(body: Any, service: str) -> Any:
    try:
        text = bytes(body).decode("utf-8")
        value = json.loads(
            text,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ValueError("non-finite JSON number: {0}".format(constant))
            ),
        )
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("{0} returned malformed JSON".format(service)) from error
    _reject_nonfinite_numbers(value)
    return value


def _reject_nonfinite_numbers(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    if isinstance(value, dict):
        for nested_value in value.values():
            _reject_nonfinite_numbers(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            _reject_nonfinite_numbers(nested_value)


def _require_positive_integer(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("{0} must be a positive integer".format(label))


def _positive_integer_or_none(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _infobox_values(entries: Iterable[Any], keys: set) -> List[str]:
    values = []
    for entry in entries:
        if not isinstance(entry, dict) or _text(entry.get("key")) not in keys:
            continue
        for text in _value_texts(entry.get("value")):
            if text not in values:
                values.append(text)
    return values


def _value_texts(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        text = _text(value.get("v"))
        return [text] if text else []
    if isinstance(value, list):
        values = []
        for item in value:
            if isinstance(item, dict):
                text = _text(item.get("v"))
                if text:
                    values.append(text)
        return values
    return []


def _first_volume_count(entries: Iterable[Any]) -> Optional[int]:
    for entry in entries:
        if not isinstance(entry, dict) or _text(entry.get("key")) not in {
            "册数",
            "冊數",
            "卷数",
            "卷數",
        }:
            continue
        for text in _value_texts(entry.get("value")):
            count = _positive_integer_or_none(text)
            if count is not None:
                return count
    return None


def _has_completed_status(entries: Iterable[Any]) -> bool:
    for entry in entries:
        if not isinstance(entry, dict) or _text(entry.get("key")) not in {
            "连载状态",
            "連載狀態",
            "状态",
            "狀態",
        }:
            continue
        if any(text in {"完结", "完結", "已完结", "已完結"} for text in _value_texts(entry.get("value"))):
            return True
    return False


def _is_transient_socket_error(error: OSError) -> bool:
    if isinstance(error, (socket.timeout, TimeoutError, ConnectionError)):
        return True
    if isinstance(error, (socket.gaierror, ssl.SSLError)):
        # Offline DNS (EAI_NONAME on macOS and DNS-less containers) and captive-portal TLS
        # failures are "not reachable right now", never "no such subject".
        return True
    return error.errno in {
        errno.EADDRNOTAVAIL,  # e.g. an IPv6 answer the host has no route for
        errno.EAGAIN,
        errno.ECONNABORTED,
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.EHOSTUNREACH,
        errno.EINTR,
        errno.ENETDOWN,
        errno.ENETRESET,
        errno.ENETUNREACH,
        errno.EPIPE,
        errno.ETIMEDOUT,
    }
