"""Manga names: the series folder and archive names the library uses, and reading them back."""
from decimal import Decimal
import re
from typing import Optional

from shutong.engine.text import is_safe_path_component, normalize_title, path_safe

from .volume import VolumeRef

__all__ = [
    "build_archive_name",
    "build_output_name",
    "is_safe_path_component",
    "normalize_title",
    "parse_chapter",
    "parse_volume",
]

_NUMBER = r"\d+(?:\.\d+)?"
_SPECIAL_PATTERN = re.compile(r"(?<![A-Za-z0-9])SP\s*0*(\d+)(?![A-Za-z0-9])", re.I)
_LATIN_RANGE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:volume|vol|v)\.?\s*(%s)\s*[-~]\s*(%s)"
    % (_NUMBER, _NUMBER),
    re.I,
)
_CJK_RANGE_PATTERN = re.compile(
    r"第?\s*(%s)\s*[-~]\s*(%s)\s*[卷巻]" % (_NUMBER, _NUMBER)
)
_LATIN_VOLUME_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:volume|vol|v)\.?\s*(%s)(?![A-Za-z0-9])" % _NUMBER,
    re.I,
)
_CJK_VOLUME_PATTERN = re.compile(r"第?\s*(%s)\s*[卷巻]" % _NUMBER)
_LATIN_CHAPTER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:chapter|chap|ch)\.?\s*(%s)(?![A-Za-z0-9])" % _NUMBER, re.I)
_CJK_CHAPTER_PATTERN = re.compile(r"第?\s*(%s)\s*[话話]" % _NUMBER)
_HASH_CHAPTER_PATTERN = re.compile(r"#\s*(%s)(?![0-9])" % _NUMBER)
_CHAPTER_RANGE_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])(?:chapter|chap|ch)\.?\s*(\d+)\s*[-~]\s*(?:(?:chapter|chap|ch)\.?\s*)?(\d+)", re.I),
    re.compile(r"第?\s*(\d+)\s*[-~]\s*(\d+)\s*[话話]"),
)


def parse_volume(source_name: str) -> Optional[VolumeRef]:
    """The volume a library file name carries (``Vol.01``, ``Vol.01-05``, ``SP01``)."""
    special_match = _SPECIAL_PATTERN.search(source_name)
    if special_match:
        return VolumeRef.special(int(special_match.group(1)))

    for pattern in (_LATIN_RANGE_PATTERN, _CJK_RANGE_PATTERN):
        range_match = pattern.search(source_name)
        if range_match:
            return VolumeRef.range(
                Decimal(range_match.group(1)), Decimal(range_match.group(2))
            )

    for pattern in (_LATIN_VOLUME_PATTERN, _CJK_VOLUME_PATTERN):
        volume_match = pattern.search(source_name)
        if volume_match:
            return VolumeRef.volume(Decimal(volume_match.group(1)))
    return None


def parse_chapter(source_name: str) -> Optional[VolumeRef]:
    """``第15话`` / ``第15話`` / ``Chap.15`` / ``Chapter 15`` / ``Ch.15`` / ``#15``; a range is not one chapter."""
    if any(pattern.search(source_name) for pattern in _CHAPTER_RANGE_PATTERNS):
        return None
    for pattern in (_CJK_CHAPTER_PATTERN, _LATIN_CHAPTER_PATTERN, _HASH_CHAPTER_PATTERN):
        match = pattern.search(source_name)
        if match:
            return VolumeRef.chapter(Decimal(match.group(1)))
    return None


def build_output_name(title: str, edition: Optional[str]) -> str:
    """Build the series folder name, including its confirmed edition when given."""
    normalized_title = normalize_title(title)
    return path_safe("{0}[{1}]".format(normalized_title, edition) if edition else normalized_title)


def build_archive_name(output_name: str, volume: VolumeRef, width: int) -> str:
    """Build a Kavita-compatible CBZ archive filename."""
    return "{0} {1}.cbz".format(output_name, volume.token(width))
