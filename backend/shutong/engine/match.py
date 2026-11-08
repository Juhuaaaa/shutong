"""Find the metadata subject for a series: chosen → automatic pick → AI suggestion, source by source."""
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError

from shutong.metadata.base import MetadataSource, MetadataUnavailable, Subject
from shutong.metadata.rank import Scored, fits_kind, is_volume_entry, match_key, pick, rank

from .ai_assist import AiSuggestion, SourceContext, _effective_threshold, choose_own_entry, choose_subject


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
    label: str = ""  # the source asked, for messages
    ai_says_none: bool = False  # the AI is sure no candidate is the work

    @property
    def none_found(self) -> bool:
        """This source does not have the work: the next source may be asked."""
        if self.subject is not None or self.retry or self.config_error or self.error:
            return False
        return (not self.candidates and not self.offered) or self.ai_says_none


@dataclass(frozen=True)
class OwnEntry:
    """Does a sub-series have its own Bangumi entry? Neither ``subject`` nor ``none_found``: nobody can tell."""
    subject: Optional[Subject] = None
    none_found: bool = False
    retry: bool = False
    config_error: bool = False
    error: Optional[str] = None
    note: str = ""


def label_of(source) -> str:
    return getattr(source, "label", None) or source.name


def _source_errors(source, error: Exception) -> Tuple[str, bool]:
    """The message for a failed request, and whether it is the user's configuration (401/403)."""
    if isinstance(error, HTTPError):
        return "{0} 返回错误：{1} {2}".format(label_of(source), error.code, error.reason), error.code in (401, 403)
    return "{0} 返回的数据无法读取：{1}".format(label_of(source), error), False


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
    except Exception as error:  # malformed responses must not abort a whole scan
        message, config_error = _source_errors(source, error)
        return OwnEntry(error=message, config_error=config_error)
    if not found:
        return OwnEntry(none_found=True)
    offered = found[:_OFFERED_LIMIT]
    key = None
    if memo is not None and context.source_folder is not None:
        key = ("own", source.name, context.source_folder, title,
               tuple(sorted(subject.subject_id for subject in offered)))
    suggestion = memo.get(key) if key is not None else None
    if suggestion is None:
        suggestion = choose_own_entry(ai, context, offered, threshold, base_title=base_title, kind=kind,
                                      item_id=item_id, source_label=label_of(source))
        if key is not None:
            memo[key] = suggestion
    if suggestion.meets_threshold:
        return OwnEntry(subject=next(s for s in offered if s.subject_id == suggestion.subject_id))
    if suggestion.none_found:
        return OwnEntry(none_found=True)
    return OwnEntry(note=suggestion.problem or "AI 说不准 {0} 上有没有这个分部的条目".format(label_of(source)))


def match_subject(
    source: MetadataSource,
    *,
    kind: str,
    title_hint: str,
    forced_id: Optional[str],
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
    label = label_of(source)
    if forced_id is None and not title_hint.strip():
        return MatchResult(None, "none", error="没有书名，无法搜索 {0}".format(label), label=label)
    found: List = []
    ranked: Tuple[Scored, ...] = ()
    try:
        if forced_id is not None:
            return MatchResult(source.get(forced_id), "rule", label=label)
        queries = list(dict.fromkeys([title_hint] + [title for title in search_titles if title.strip()]))
        for query in queries:
            results = source.search(query, kind)
            query_ranked = rank(query, results, kind)
            chosen = pick(query_ranked)
            if chosen is not None:
                return MatchResult(chosen, "auto", query_ranked, label=label)
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
                return MatchResult(chosen, "auto", query_ranked, label=label)
    except MetadataUnavailable as error:
        return MatchResult(None, "none", retry=True, error=str(error), label=label)
    except Exception as error:  # 404s and malformed responses must not abort a whole scan
        message, config_error = _source_errors(source, error)
        return MatchResult(None, "none", error=message, config_error=config_error, label=label)
    if ai is None or context is None:
        return MatchResult(None, "none", ranked, label=label)
    offered = [scored.subject for scored in ranked]
    offered += [s for s in found if fits_kind(s, kind) and s not in offered]
    offered = (offered or [s for s in found if not is_volume_entry(s)])[:_OFFERED_LIMIT]
    key = None
    if memo is not None and context.source_folder is not None:
        key = ("subject", source.name, context.source_folder, title_hint,
               tuple(sorted(s.subject_id for s in offered)))
    suggestion = memo.get(key) if key is not None else None
    if suggestion is None:
        suggestion = choose_subject(ai, context, offered, threshold, kind=kind, item_id=item_id, source_label=label)
        if key is not None:
            memo[key] = suggestion
    if suggestion.meets_threshold:
        subject = next(s for s in offered if s.subject_id == suggestion.subject_id)
        return MatchResult(subject, "ai", ranked, suggestion, offered=tuple(offered), label=label)
    says_none = suggestion.problem is None and suggestion.subject_id is None \
        and suggestion.confidence >= _effective_threshold(threshold)
    return MatchResult(None, "none", ranked, suggestion, offered=tuple(offered), label=label, ai_says_none=says_none)


def match_across(sources: Sequence[MetadataSource], **options) -> MatchResult:
    """Ask the sources in order; only a source that surely lacks the work passes it on to the next.

    A source that is away, misconfigured or unsure stops here: the item waits or goes to review rather than
    quietly taking another source's metadata. When none has it, the first source's answer is returned.
    """
    first = None
    for source in sources:
        result = match_subject(source, **options)
        if not result.none_found:
            return result
        first = first or result
    if first is None:
        return MatchResult(None, "none", error="没有可用的数据源")
    return first

