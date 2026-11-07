"""AI suggestions for a series: pick a Bangumi candidate, or propose title + edition.

Ported from the legacy manga ai_matcher. Privacy: only basenames, the title hint,
edition signals and compact candidate facts are sent. Every failure becomes a
suggestion with a ``problem`` instead of an exception.
"""
from dataclasses import dataclass, replace
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence, Set, Tuple

from shutong.ai.openai_compat import AiError
from shutong.engine.text import is_safe_path_component
from shutong.metadata.base import Subject

_TEXT_LIMIT = 200
_WRITER_LIMIT = 8
_CONFIDENCE_FLOOR = 0.8
_KIND_LABELS = {"manga": "漫画 (manga)", "novel": "轻小说 (light novel)"}


@dataclass(frozen=True)
class SourceContext:
    source_folder: Optional[str]
    names: Tuple[str, ...]
    title_hint: str
    edition_signals: Tuple[str, ...] = ()

    def payload(self) -> Dict[str, Any]:
        return {
            "source_folder": _basename(self.source_folder) if self.source_folder else "",
            "file_names": [_basename(name) for name in self.names],
            "normalized_title": _bounded(self.title_hint),
            "edition_signals": list(_normalized_signals(self.edition_signals)),
        }


@dataclass(frozen=True)
class AiSuggestion:
    subject_id: Optional[str] = None
    title: Optional[str] = None
    edition: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""
    meets_threshold: bool = False
    call_id: Optional[int] = None
    problem: Optional[str] = None
    none_found: bool = False  # sure that no candidate fits (only ever set by choose_own_entry)


def choose_subject(ai, context: SourceContext, candidates: Sequence[Subject], threshold: float, *,
                   kind: str, item_id: Optional[int] = None, source_label: str = "Bangumi") -> AiSuggestion:
    system = (
        "You are a precise {0} metadata matcher. Select exactly one supplied {1} candidate "
        "or null. Return only JSON with subject_id, confidence, and reason."
    ).format(_KIND_LABELS.get(kind, kind), source_label)
    return _choose(ai, context, candidates, threshold, system, {}, item_id)


def choose_own_entry(ai, context: SourceContext, candidates: Sequence[Subject], threshold: float, *,
                     base_title: str, kind: str, item_id: Optional[int] = None,
                     source_label: str = "Bangumi") -> AiSuggestion:
    """Does this sub-series have a Bangumi entry of its own? ``none_found``: confidently not."""
    system = (
        "You are a precise {0} metadata matcher. The files are a sub-series of the work named in base_title "
        "(a later part, a spin-off, a side story); normalized_title is the sub-series. Select the supplied "
        "{1} candidate that is this very sub-series. The entry of the original work or of another part "
        "does not count, however closely its name matches: answer null then. confidence is how sure you are "
        "of your answer, null included. Return only JSON with subject_id, confidence, and reason."
    ).format(_KIND_LABELS.get(kind, kind), source_label)
    suggestion = _choose(ai, context, candidates, threshold, system, {"base_title": _bounded(base_title)}, item_id)
    if suggestion.problem is None and suggestion.subject_id is None \
            and suggestion.confidence >= _effective_threshold(threshold):
        return replace(suggestion, none_found=True)
    return suggestion


def _choose(ai, context: SourceContext, candidates: Sequence[Subject], threshold: float, system: str,
            extra: Dict[str, Any], item_id: Optional[int]) -> AiSuggestion:
    unique = {}
    for candidate in candidates:
        unique.setdefault(candidate.subject_id, candidate)
    if not unique:
        return AiSuggestion(problem="没有候选条目")
    payload = context.payload()
    payload.update(extra)
    payload["candidates"] = [_candidate_json(candidate) for candidate in unique.values()]
    response, call_id, problem = _ask(ai, "choose_subject", system, payload, item_id)
    if problem:
        return AiSuggestion(call_id=call_id, problem=problem)
    try:
        _require_exact_fields(response, {"subject_id", "confidence", "reason"})
        subject_id = response["subject_id"]
        confidence = _validate_confidence(response["confidence"])
        reason = _validate_reason(response["reason"])
        if subject_id is not None:
            if isinstance(subject_id, bool) or not isinstance(subject_id, (int, str)):
                raise ValueError("subject_id must be one of the candidates' ids or null")
            subject_id = str(subject_id).strip()
            if subject_id not in unique:
                raise ValueError("subject_id is not present in candidates")
    except ValueError as error:
        return AiSuggestion(call_id=call_id, problem="AI 返回的内容不符合要求：{0}".format(error))
    meets = subject_id is not None and confidence >= _effective_threshold(threshold)
    return AiSuggestion(subject_id=subject_id, confidence=confidence, reason=reason,
                        meets_threshold=meets, call_id=call_id)


def _candidate_json(candidate: Subject) -> Dict[str, Any]:
    entry = {
        "subject_id": candidate.subject_id,
        "name": _bounded(candidate.name),
        "name_cn": _bounded(candidate.name_cn),
        "writers": [_bounded(writer) for writer in candidate.writers[:_WRITER_LIMIT]],
        "publisher": _bounded(candidate.publisher),
    }
    if candidate.aliases:  # sources without Chinese names: English and romanized names help
        entry["other_names"] = [_bounded(name) for name in candidate.aliases[:_WRITER_LIMIT]]
    return entry


def _ask(ai, purpose, system, payload, item_id):
    try:
        response, call_id = ai.complete_json(purpose, system, payload, item_id=item_id)
    except AiError:
        return None, None, "AI 调用失败或返回的内容不符合要求"
    return response, call_id, None


def _effective_threshold(threshold: float) -> float:
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    return max(float(threshold), _CONFIDENCE_FLOOR)


def _safe_name(value: str) -> bool:
    # Same rule as the legacy matcher: one path component, no surrounding/control whitespace.
    return is_safe_path_component(value) and value == value.strip() and not any(
        character in value for character in "\t\n\r")


def _require_exact_fields(response: Any, fields: Set[str]) -> None:
    if not isinstance(response, dict):
        raise ValueError("AI result must be a JSON object")
    if set(response) != fields:
        raise ValueError("AI result has missing or unexpected fields")


def _validate_confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("confidence must be a number")
    confidence = float(value)
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be finite and between 0 and 1")
    return confidence


def _validate_reason(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("reason must be a non-empty string")
    return value


def _normalized_signals(values: Iterable[str]) -> Tuple[str, ...]:
    signals = []
    for value in values:
        if isinstance(value, str) and value.strip() and value.strip() not in signals:
            signals.append(value.strip())
    return tuple(sorted(signals))


def _basename(value: str) -> str:
    return _bounded(Path(str(value)).name)


def _bounded(value: str) -> str:
    return str(value)[:_TEXT_LIMIT]
