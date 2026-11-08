"""English summaries (AniList's) in Chinese: the AI translates each once, and the translation is cached.

Only the summary text is sent. A translation that fails leaves the original: organizing never waits on it.
"""
from dataclasses import replace
import hashlib
import logging
import re
from typing import Optional

from shutong.metadata.base import Subject
from shutong.store.cache import CacheStore

log = logging.getLogger("shutong.translate")
_CJK = re.compile(r"[㐀-鿿]")
_TTL_SECONDS = 365 * 24 * 60 * 60
_SYSTEM = (
    "Translate the summary of a manga or light novel into natural Simplified Chinese, as a Chinese publisher "
    "would write it. Keep names of people and places as they are usually written in Chinese editions, or as "
    "given when unsure. Keep paragraph breaks. Return only JSON: {\"summary\": \"...\"}."
)
_MAX_CHARS = 6000


def localize(subject: Subject, *, ai, cache: CacheStore, enabled: bool) -> Subject:
    """The subject with its summary in Chinese, when it was written in another language."""
    summary = subject.summary.strip()
    # Bangumi is left as it is: its few Japanese summaries were there before, and refreshing must not change them.
    if not enabled or ai is None or not summary or subject.source in ("bangumi", "none") or _mostly_chinese(summary):
        return subject
    key = "translate:zh:{0}:{1}:{2}".format(subject.source, subject.subject_id,
                                            hashlib.sha256(summary.encode("utf-8")).hexdigest()[:16])
    cached = cache.get(key)
    if isinstance(cached, dict) and isinstance(cached.get("summary"), str) and cached["summary"].strip():
        return replace(subject, summary=cached["summary"])
    translated = _translate(ai, subject, summary[:_MAX_CHARS])
    if translated is None:
        return subject
    cache.put(key, {"summary": translated}, ttl_seconds=_TTL_SECONDS)
    return replace(subject, summary=translated)


def _translate(ai, subject: Subject, summary: str) -> Optional[str]:
    try:
        response, _ = ai.complete_json("translate", _SYSTEM, {"title": subject.display_title, "summary": summary})
    except Exception as error:  # AiError, or a provider that misbehaves: the original summary stays
        log.warning("翻译简介失败，保留原文：%s（%s）", subject.display_title, error)
        return None
    text = response.get("summary") if isinstance(response, dict) else None
    if not isinstance(text, str) or not text.strip():
        log.warning("AI 返回的译文不能用，保留原文：%s", subject.display_title)
        return None
    return text.strip()


def _mostly_chinese(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    return bool(letters) and sum(1 for char in letters if _CJK.match(char)) * 2 >= len(letters)
