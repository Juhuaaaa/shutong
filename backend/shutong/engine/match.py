"""Find the metadata subject for a series: rule → automatic pick → AI suggestion."""
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError

from shutong.metadata.base import MetadataSource, MetadataUnavailable, Subject
from shutong.metadata.rank import Scored, fits_kind, is_volume_entry, match_key, pick, rank

from .ai_assist import AiSuggestion, SourceContext, choose_own_entry, choose_subject


_OFFERED_LIMIT = 15


@dataclass(frozen=True)
class MatchResult:
    subject: Optional[Subject]
    method: str  # "rule" | "auto" | "ai" | "none"
    candidates: Tuple[Scored, ...] = ()
    suggestion: Optional[AiSuggestion] = None
    retry: bool = False  # the source is temporarily unavailable: try later, do not send to review
    error: Optional[str] = None
    config_error: bool = False  # e.g. a bad Bangumi token: tell the user, do not blame the item
    offered: Tuple[Subject, ...] = ()  # what the AI was asked to choose from


@dataclass(frozen=True)
class OwnEntry:
    """Does a sub-series have its own Bangumi entry? Neither ``subject`` nor ``none_found``: nobody can tell."""
    subject: Optional[Subject] = None
    none_found: bool = False
    retry: bool = False
    config_error: bool = False
    error: Optional[str] = None
    note: str = ""


def _namesake_originals(title: str, found: Sequence[Subject], kind: str) -> List[str]:
    """Original names of same-titled entries of the other kind (the novel's adaptation, say).

    Chinese names differ between a work's entries (我的女友是老师 / 我的女友老师); the original name does not.
    """
    wanted = match_key(title)
    names = [subject.name for subject in found
             if subject.name and match_key(subject.name_cn) == wanted
             and not fits_kind(subject, kind) and not is_volume_entry(subject)]
    return list(dict.fromkeys(names))


def find_own_entry(
    source: MetadataSource,
    *,
    kind: str,
    title: str,
    base_title: str,
    search_titles: Sequence[str],
    context: SourceContext,
    ai,
    threshold: float,
    item_id: Optional[int] = None,
    memo: Optional[Dict[tuple, AiSuggestion]] = None,
) -> OwnEntry:
    """The search alone cannot answer this: the original often is the clear winner for a sub-series' name."""
    found: List[Subject] = []
    try:
        for query in dict.fromkeys([title] + [name for name in search_titles if name.strip()]):
            known = {subject.subject_id for subject in found}
            found.extend(subject for subject in source.search(query, kind)
                         if subject.subject_id not in known and fits_kind(subject, kind))
    except MetadataUnavailable as error:
        return OwnEntry(retry=True, error=str(error))
    except HTTPError as error:
        return OwnEntry(error="Bangumi 返回错误：{0} {1}".format(error.code, error.reason),
                        config_error=error.code in (401, 403))
    except Exception as error:  # malformed responses must not abort a whole scan
        return OwnEntry(error="Bangumi 返回的数据无法读取：{0}".format(error))
    if not found:
        return OwnEntry(none_found=True)
    offered = found[:_OFFERED_LIMIT]
    key = None
    if memo is not None and context.source_folder is not None:
        key = ("own", context.source_folder, title, tuple(sorted(subject.subject_id for subject in offered)))
    suggestion = memo.get(key) if key is not None else None
    if suggestion is None:
        suggestion = choose_own_entry(ai, context, offered, threshold, base_title=base_title, kind=kind, item_id=item_id)
        if key is not None:
            memo[key] = suggestion
    if suggestion.meets_threshold:
        return OwnEntry(subject=next(s for s in offered if s.subject_id == suggestion.subject_id))
    if suggestion.none_found:
        return OwnEntry(none_found=True)
    return OwnEntry(note=suggestion.problem or "AI 说不准 Bangumi 上有没有这个分部的条目")


def match_subject(
    source: MetadataSource,
    *,
    kind: str,
    title_hint: str,
    forced_bgm: Optional[int],
    search_titles: Sequence[str] = (),
    context: Optional[SourceContext] = None,
    ai=None,
    threshold: float = 0.95,
    item_id: Optional[int] = None,
    memo: Optional[Dict[tuple, AiSuggestion]] = None,
) -> MatchResult:
    """``method == "ai"`` only means the AI suggestion met the threshold; adopting it is the caller's call.

    Never raises for source problems: unavailable → ``retry``; 401/403 → ``config_error``;
    anything else (404, malformed response) → ``error`` and the item goes to review.
    ``search_titles`` (original or other names) are searched in turn when the title finds no clear winner.
    ``memo`` reuses one AI answer for every volume of a source folder (one call per series, not per volume).
    """
    if forced_bgm is None and not title_hint.strip():
        return MatchResult(None, "none", error="没有书名，无法搜索 Bangumi")
    found: List = []
    ranked: Tuple[Scored, ...] = ()
    try:
        if forced_bgm is not None:
            return MatchResult(source.get(forced_bgm), "rule")
        queries = list(dict.fromkeys([title_hint] + [title for title in search_titles if title.strip()]))
        for query in queries:
            results = source.search(query, kind)
            query_ranked = rank(query, results, kind)
            chosen = pick(query_ranked)
            if chosen is not None:
                return MatchResult(chosen, "auto", query_ranked)
            known = {subject.subject_id for subject in found}
            found.extend(subject for subject in results if subject.subject_id not in known)
            ranked += tuple(scored for scored in query_ranked
                            if scored.subject.subject_id not in {s.subject.subject_id for s in ranked})
        for query in _namesake_originals(title_hint, found, kind):
            if query in queries:
                continue
            query_ranked = rank(query, source.search(query, kind), kind)
            chosen = pick(query_ranked)
            if chosen is not None:
                return MatchResult(chosen, "auto", query_ranked)
    except MetadataUnavailable as error:
        return MatchResult(None, "none", retry=True, error=str(error))
    except HTTPError as error:
        return MatchResult(None, "none", error="Bangumi 返回错误：{0} {1}".format(error.code, error.reason),
                           config_error=error.code in (401, 403))
    except Exception as error:  # malformed responses must not abort a whole scan
        return MatchResult(None, "none", error="Bangumi 返回的数据无法读取：{0}".format(error))
    if ai is None or context is None:
        return MatchResult(None, "none", ranked)
    offered = [scored.subject for scored in ranked]
    offered += [s for s in found if fits_kind(s, kind) and s not in offered]
    offered = (offered or [s for s in found if not is_volume_entry(s)])[:_OFFERED_LIMIT]
    key = None
    if memo is not None and context.source_folder is not None:
        key = ("subject", context.source_folder, title_hint, tuple(sorted(s.subject_id for s in offered)))
    suggestion = memo.get(key) if key is not None else None
    if suggestion is None:
        suggestion = choose_subject(ai, context, offered, threshold, kind=kind, item_id=item_id)
        if key is not None:
            memo[key] = suggestion
    if suggestion.meets_threshold:
        subject = next(s for s in offered if s.subject_id == suggestion.subject_id)
        return MatchResult(subject, "ai", ranked, suggestion, offered=tuple(offered))
    return MatchResult(None, "none", ranked, suggestion, offered=tuple(offered))

