"""ComicInfo.xml for manga CBZ outputs (ComicInfo v2.1 subset Kavita reads)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import re
from typing import Dict, Optional, Sequence
from xml.etree import ElementTree
import zipfile

from .volume import VolumeRef

_DATE_PATTERN = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")


@dataclass(frozen=True)
class ComicMetadata:
    series_name: str
    volume: VolumeRef
    subject_id: Optional[int] = None
    localized_series: str = ""
    title: str = ""
    summary: str = ""
    writers: Sequence[str] = ()
    publisher: str = ""
    release_date: Optional[str] = None
    genres: Sequence[str] = ()
    language: str = "zh"
    manga_direction: str = "YesAndRightToLeft"
    completed: bool = False
    total_volumes: Optional[int] = None


def build_comic_info(metadata: ComicMetadata, page_count: object) -> bytes:
    """Build a ComicInfo v2.1 XML document without external entities."""
    root = ElementTree.Element("ComicInfo")
    _add_text(root, "Series", metadata.series_name)
    _add_text(root, "LocalizedSeries", metadata.localized_series)
    _add_text(root, "SeriesSort", metadata.series_name)
    _add_text(root, "Title", metadata.title)
    _add_volume(root, metadata.volume)

    if metadata.completed is True and _is_positive_integer(metadata.total_volumes):
        _add_text(root, "Count", metadata.total_volumes)

    _add_text(root, "Summary", metadata.summary)
    _add_text(root, "Writer", _join_unique(metadata.writers))
    _add_text(root, "Publisher", metadata.publisher)
    _add_release_date(root, metadata.release_date)

    tags = _join_unique(metadata.genres)
    _add_text(root, "Genre", tags)
    _add_text(root, "Tags", tags)
    _add_text(root, "LanguageISO", metadata.language)
    _add_text(root, "Manga", metadata.manga_direction)

    if _is_positive_integer(metadata.subject_id):
        _add_text(root, "Web", subject_web_url(metadata.subject_id))
    if _is_nonnegative_integer(page_count):
        _add_text(root, "PageCount", page_count)

    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def read_comic_info(cbz: Path) -> Dict[str, str]:
    """Top-level ComicInfo.xml fields of a CBZ as ``{tag: text}``."""
    with zipfile.ZipFile(cbz) as archive:
        root = ElementTree.fromstring(archive.read("ComicInfo.xml"))
    return {child.tag: (child.text or "") for child in root}


def subject_web_url(subject_id: int) -> str:
    """The public bgm.tv page Kavita links to from a series."""
    return "https://bgm.tv/subject/{0}".format(subject_id)


def _add_volume(root: ElementTree.Element, volume: VolumeRef) -> None:
    _validate_volume(volume)
    if volume.kind == "special":
        _add_text(root, "Number", "SP{0:02d}".format(volume.special_number))
        _add_text(root, "Format", "Special")
        return

    if volume.kind == "chapter":
        _add_text(root, "Number", chapter_number(volume))
    elif volume.kind == "volume":
        _add_text(root, "Volume", _format_decimal(volume.start))
    else:
        start = _format_decimal(volume.start)
        end = _format_decimal(volume.end)
        _add_text(root, "Volume", "{0}-{1}".format(start, end))


def chapter_number(volume: VolumeRef) -> str:
    """ComicInfo ``Number`` for a chapter: ``15``, or ``1-40`` for a run of chapters in one file."""
    if volume.end is not None:
        return "{0}-{1}".format(_format_decimal(volume.start), _format_decimal(volume.end))
    return _format_decimal(volume.start)


def _add_release_date(root: ElementTree.Element, release_date: Optional[str]) -> None:
    """``2016-08-01``, or just ``2016-08`` / ``2016`` when that is all anyone knows."""
    if not isinstance(release_date, str) or not _DATE_PATTERN.fullmatch(release_date):
        return
    for layout, fields in (("%Y-%m-%d", ("Year", "Month", "Day")), ("%Y-%m", ("Year", "Month")), ("%Y", ("Year",))):
        try:
            parsed = datetime.strptime(release_date, layout)
        except ValueError:
            continue
        for field in fields:
            _add_text(root, field, getattr(parsed, field.lower()))
        return


def _add_text(root: ElementTree.Element, tag: str, value: object) -> None:
    if value is None:
        return
    text = "".join(character for character in str(value) if _is_xml_character(character))
    text = text.strip()
    if text:
        ElementTree.SubElement(root, tag).text = text


def _validate_volume(volume: object) -> None:
    if not isinstance(volume, VolumeRef):
        raise ValueError("invalid volume reference")
    if volume.kind in ("volume", "chapter"):
        start = _require_positive_decimal(volume.start)
        if volume.kind == "chapter" and volume.end is not None and _require_positive_decimal(volume.end) <= start:
            raise ValueError("invalid chapter range")
        return
    if volume.kind == "range":
        start = _require_positive_decimal(volume.start)
        end = _require_positive_decimal(volume.end)
        if end < start:
            raise ValueError("invalid volume range")
        return
    if volume.kind == "special" and _is_positive_integer(volume.special_number):
        return
    raise ValueError("invalid volume reference")


def _require_positive_decimal(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError("invalid volume bound")
    return value


def _format_decimal(value: object) -> str:
    value = _require_positive_decimal(value)
    text = format(value, "f")
    # Only the fractional part may drop trailing zeros: "19.50" -> "19.5",
    # while the integer "10" must keep its significant trailing zero.
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _is_xml_character(character: str) -> bool:
    code_point = ord(character)
    if code_point in (0x9, 0xA, 0xD):
        return True
    if not (0x20 <= code_point <= 0xD7FF or 0xE000 <= code_point <= 0x10FFFF):
        return False
    return not (0xFDD0 <= code_point <= 0xFDEF or code_point & 0xFFFF in (0xFFFE, 0xFFFF))


def _join_unique(values: Sequence[str]) -> str:
    seen = set()
    unique = []
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return ", ".join(unique)


def _is_positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
