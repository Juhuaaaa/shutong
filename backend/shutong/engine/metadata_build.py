"""Turn a matched subject into the metadata each kind writes into its output file."""
from dataclasses import asdict
from decimal import Decimal
import re
from typing import Any, Dict, Mapping, Optional, Tuple

from shutong.engine.kinds.manga.comicinfo import ComicMetadata
from shutong.engine.kinds.manga.volume import VolumeRef
from shutong.engine.kinds.novel.epub import SPECIAL_VOLUME_INDEX, KavitaMetadata
from shutong.engine.kinds.novel.naming import NovelVolume
from shutong.engine.recognition import Directives
from shutong.metadata.base import Subject
from shutong.metadata.rank import match_key

_EXCLUDED_GENRES = frozenset({"小说", "小说系列", "系列", "日本", "存盘", "搜索用", "轻小说"})
_YEAR = re.compile(r"^\d{4}$")
_RELEASE_DATE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")


def select_genres(subject: Subject, limit: int = 10) -> Tuple[str, ...]:
    """Clean genre tags (legacy novel rules): no years, authors, titles or catalogue noise."""
    author_names = {match_key(name) for name in subject.writers}
    title_names = {match_key(subject.name), match_key(subject.name_cn)} - {""}
    selected = []
    for genre in subject.genres:
        text = genre.strip()
        if not text or text in _EXCLUDED_GENRES or _YEAR.match(text) or text.isdigit():
            continue
        if match_key(text) in author_names or match_key(text) in title_names:
            continue
        if text not in selected:
            selected.append(text)
        if len(selected) >= limit:
            break
    return tuple(selected)


def normalize_release_date(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return ""
    match = _RELEASE_DATE.match(value.strip())
    if not match:
        return ""
    year, month, day = match.groups()
    if month and day:
        return "{0}-{1}-{2}".format(year, month, day)
    if month:
        return "{0}-{1}".format(year, month)
    return year


def manga_metadata(series_name: str, volume: VolumeRef, subject: Subject, directives: Directives,
                   width: int) -> ComicMetadata:
    return ComicMetadata(
        series_name=series_name,
        volume=volume,
        subject_id=subject.subject_id,
        localized_series=subject.display_title,
        title=volume.token(width),
        summary=subject.summary,
        writers=tuple(subject.writers),
        publisher=subject.publisher,
        release_date=subject.release_date,
        genres=tuple(subject.genres),
        language=directives.lang or "zh",
        manga_direction=directives.direction or "YesAndRightToLeft",
        completed=subject.completed,
        total_volumes=subject.total_volumes,
    )


def novel_metadata(series_name: str, volume: NovelVolume, subject: Subject, details: Mapping[str, Any],
                   directives: Directives, *, first_volume: bool, fallback_title: str) -> KavitaMetadata:
    title = str(details.get("title") or "").strip() or fallback_title
    index = volume.number if volume.kind == "volume" else Decimal(SPECIAL_VOLUME_INDEX)
    return KavitaMetadata(
        series=series_name,
        series_index=index,
        title=title,
        language=directives.lang or "zh",
        authors=tuple(subject.writers),
        publisher=subject.publisher,
        genres=select_genres(subject),
        description=" ".join(subject.summary.split()) if first_volume else "",
        date=normalize_release_date(subject.release_date),
        web_url=subject.web_url,
    )


def volume_from_key(kind: str, key: str):
    if kind == "novel":
        if key == "special":
            return NovelVolume.special()
        return NovelVolume.volume(Decimal(key.split(":", 1)[1]))
    prefix, _, value = key.partition(":")
    if prefix == "special":
        return VolumeRef.special(int(value))
    if prefix == "range":
        start, end = value.split("-", 1)
        return VolumeRef.range(Decimal(start), Decimal(end))
    if prefix == "chapter":
        start, _, end = value.partition("-")
        return VolumeRef.chapter(Decimal(start), Decimal(end) if end else None)
    return VolumeRef.volume(Decimal(value))


def metadata_to_json(metadata) -> Dict[str, Any]:
    data = asdict(metadata)
    if isinstance(metadata, ComicMetadata):
        data["volume"] = metadata.volume.key()
    else:
        data["series_index"] = str(metadata.series_index)
    for key, value in list(data.items()):
        if isinstance(value, tuple):
            data[key] = list(value)
    return data


def metadata_from_json(kind: str, data: Mapping[str, Any]):
    values = dict(data)
    if kind == "manga":
        values["volume"] = volume_from_key("manga", values["volume"])
        for key in ("writers", "genres"):
            values[key] = tuple(values[key])
        return ComicMetadata(**values)
    values["series_index"] = Decimal(values["series_index"])
    for key in ("authors", "genres"):
        values[key] = tuple(values[key])
    return KavitaMetadata(**values)
