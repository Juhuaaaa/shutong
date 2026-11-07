"""Score metadata candidates against a title hint (logic from the legacy novel selector)."""
import re
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from .base import Subject

_NOVEL_PLATFORM = "小说"
_MANGA_PLATFORM = "漫画"
_NOVEL_TAGS = frozenset({"轻小说", "小说"})
_MANGA_TAGS = frozenset({"漫画", "漫画系列", "漫画版"})
_PICK_THRESHOLD = 0.8
# 「… (1)」「…（2）」「…(3)」「… 第3巻」「… 5」: the name of one numbered volume.
_VOLUME_SUFFIX = re.compile(r"(?:[(（]\s*\d+\s*[)）]|\s第?\s*\d+\s*[巻卷册冊集]?|第\s*\d+\s*[巻卷册冊集])\s*$")


@dataclass(frozen=True)
class Scored:
    subject: Subject
    score: float


def match_key(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.casefold()
    return "".join(
        character
        for character in normalized
        if character.isalnum() or "一" <= character <= "鿿"
    )


def similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    shorter, longer = sorted((left, right), key=len)
    if shorter in longer and len(shorter) >= max(2, len(longer) // 2):
        return 0.9
    return 0.0


def is_volume_entry(subject: Subject) -> bool:
    """One numbered volume of a series (Bangumi lists tankobon separately), not the series itself."""
    if subject.series is not False:
        return False
    return any(_VOLUME_SUFFIX.search(name) for name in (subject.name, subject.name_cn) if name)


def fits_kind(subject: Subject, kind: str) -> bool:
    if is_volume_entry(subject):
        return False  # organizing a series under its volume 1 entry mislabels every other volume
    # The platform field is authoritative; tags are user-voted and a novel
    # subject often also carries 漫画 because of its adaptation.
    genres = set(subject.genres)
    if kind == "novel":
        if subject.platform:
            return subject.platform == _NOVEL_PLATFORM
        if genres & _MANGA_TAGS:
            return False
        if genres & _NOVEL_TAGS:
            return True
        return subject.total_volumes is not None
    if subject.platform:
        return subject.platform == _MANGA_PLATFORM
    if genres & _NOVEL_TAGS:
        return False
    if genres & _MANGA_TAGS:
        return True
    return subject.total_volumes is not None


def rank(title_hint: str, candidates: Sequence[Subject], kind: str) -> Tuple[Scored, ...]:
    hint = match_key(title_hint)
    if not hint:
        return ()
    scored = []
    for candidate in candidates:
        if not fits_kind(candidate, kind):
            continue
        score = max(similarity(hint, match_key(candidate.name_cn)),
                    similarity(hint, match_key(candidate.name)))
        if score > 0:
            scored.append(Scored(candidate, score))
    scored.sort(key=lambda item: (item.score, item.subject.total_volumes or 0), reverse=True)
    return tuple(scored)


def pick(ranked: Sequence[Scored]) -> Optional[Subject]:
    """The clear winner, or None when the best is weak or tied on score and volumes."""
    if not ranked or ranked[0].score < _PICK_THRESHOLD:
        return None
    if len(ranked) > 1:
        best, runner_up = ranked[0], ranked[1]
        if (runner_up.score == best.score
                and (runner_up.subject.total_volumes or 0) == (best.subject.total_volumes or 0)):
            return None
    return ranked[0].subject
