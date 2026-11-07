"""Item lifecycle shared by every media kind."""
from enum import Enum


class ItemStatus(str, Enum):
    DISCOVERED = "discovered"
    PARSED = "parsed"
    MATCHED = "matched"
    PLANNED = "planned"
    NEEDS_REVIEW = "needs_review"
    READY = "ready"
    BUILDING = "building"
    PUBLISHED = "published"
    FAILED = "failed"
    DUPLICATE = "duplicate"
    CANCELLED = "cancelled"


class ReviewReason(str, Enum):
    NAMING = "naming"
    VOLUME = "volume"
    METADATA = "metadata"
    CONFLICT = "conflict"


_S = ItemStatus

TRANSITIONS: dict[ItemStatus, frozenset[ItemStatus]] = {
    _S.DISCOVERED: frozenset({_S.PARSED, _S.FAILED, _S.DUPLICATE, _S.CANCELLED}),
    _S.PARSED: frozenset({_S.MATCHED, _S.NEEDS_REVIEW, _S.FAILED, _S.CANCELLED}),
    # MATCHED -> DUPLICATE: the library's existing volumes are only known while planning.
    # MATCHED -> PARSED: a scan interrupted before planning is redone on the next scan.
    # MATCHED -> PUBLISHED: an existing library file with matching metadata is claimed, not rebuilt.
    _S.MATCHED: frozenset({_S.PARSED, _S.PLANNED, _S.NEEDS_REVIEW, _S.DUPLICATE, _S.PUBLISHED, _S.FAILED,
                           _S.CANCELLED}),
    _S.PLANNED: frozenset({_S.READY, _S.NEEDS_REVIEW, _S.CANCELLED}),
    # NEEDS_REVIEW / PUBLISHED / CANCELLED -> PARSED: confirmed in review, reorganized or revived; planned again.
    _S.NEEDS_REVIEW: frozenset({_S.PARSED, _S.PLANNED, _S.READY, _S.CANCELLED}),
    _S.READY: frozenset({_S.BUILDING, _S.NEEDS_REVIEW, _S.CANCELLED}),
    # BUILDING -> READY covers both cancellation and startup recovery.
    _S.BUILDING: frozenset({_S.PUBLISHED, _S.FAILED, _S.NEEDS_REVIEW, _S.READY}),
    # PUBLISHED -> DUPLICATE: another source took its place in the library (the library's overwrite policy).
    _S.PUBLISHED: frozenset({_S.READY, _S.PARSED, _S.DUPLICATE}),
    # FAILED -> READY retries a failed build; FAILED -> PARSED redoes a failed scan step.
    _S.FAILED: frozenset({_S.READY, _S.PARSED}),
    _S.CANCELLED: frozenset({_S.READY, _S.PARSED}),
    # DUPLICATE -> PARSED: the user disagrees and asks for the item to be planned again.
    _S.DUPLICATE: frozenset({_S.PARSED}),
}


class InvalidTransition(ValueError):
    pass


def check_transition(current: ItemStatus, target: ItemStatus) -> None:
    if target not in TRANSITIONS[current]:
        raise InvalidTransition("{0} -> {1}".format(current.value, target.value))
