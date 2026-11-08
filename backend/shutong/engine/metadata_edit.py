"""Change the metadata of organized files in place: no repacking, the pages stay byte for byte."""
from dataclasses import dataclass, replace
from datetime import date
import os
from pathlib import Path
import re
import secrets
import shutil
from typing import Any, Mapping, Tuple, Union
import zipfile

from shutong.engine.kinds.manga.cbz import verify_cbz
from shutong.engine.kinds.manga.comicinfo import ComicMetadata, build_comic_info
from shutong.engine.kinds.novel.epub import KavitaMetadata, write_metadata
from shutong.engine.metadata_build import (comic_subject_id, comic_web_url, normalize_release_date,
                                           select_genres)
from shutong.metadata.base import Subject

Metadata = Union[ComicMetadata, KavitaMetadata]

_DATE = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$")
_TEXT_LIMIT = 200
_SUMMARY_LIMIT = 5000
_LIST_LIMIT = 20


def _text(value: Any, limit: int, label: str) -> str:
    text = " ".join(str(value or "").split()) if limit <= _TEXT_LIMIT else str(value or "").strip()
    if len(text) > limit:
        raise ValueError("{0}太长了（最多 {1} 个字）".format(label, limit))
    return text


def _names(values: Any, label: str) -> Tuple[str, ...]:
    if isinstance(values, str):
        values = re.split(r"[,，、;；]", values)
    found = []
    for value in values or ():
        text = _text(value, _TEXT_LIMIT, label)
        if text and text not in found:
            found.append(text)
    if len(found) > _LIST_LIMIT:
        raise ValueError("{0}最多 {1} 个".format(label, _LIST_LIMIT))
    return tuple(found)


def _date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _DATE.match(text)
    if not match:
        raise ValueError("发售日期要写成 2016、2016-08 或 2016-08-01")
    year, month, day = (int(part) if part else None for part in match.groups())
    try:
        date(year, month or 1, day or 1)
    except ValueError:
        raise ValueError("发售日期要写成 2016、2016-08 或 2016-08-01") from None
    parts = ["{0:04d}".format(year)] + ["{0:02d}".format(part) for part in (month, day) if part]
    return "-".join(parts)


@dataclass(frozen=True)
class ManualMetadata:
    """What a person fills in for a book Bangumi does not have (or has wrong)."""

    localized_series: str = ""
    writers: Tuple[str, ...] = ()
    publisher: str = ""
    release_date: str = ""
    genres: Tuple[str, ...] = ()
    summary: str = ""
    illustrators: Tuple[str, ...] = ()  # light novels only: ComicInfo has the artists among the writers

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ManualMetadata":
        manual = cls(
            localized_series=_text(data.get("localized_series"), _TEXT_LIMIT, "原名"),
            writers=_names(data.get("writers"), "作者"),
            publisher=_text(data.get("publisher"), _TEXT_LIMIT, "出版社"),
            release_date=_date(data.get("release_date")),
            genres=_names(data.get("genres"), "标签"),
            summary=_text(data.get("summary"), _SUMMARY_LIMIT, "简介"),
            illustrators=_names(data.get("illustrators"), "插画"),
        )
        if manual == cls():
            raise ValueError("至少填一项元数据")
        return manual

    def to_json(self) -> dict:
        return {"localized_series": self.localized_series, "writers": list(self.writers), "publisher": self.publisher,
                "release_date": self.release_date, "genres": list(self.genres), "summary": self.summary,
                "illustrators": list(self.illustrators)}


def apply_manual(metadata: Metadata, manual: ManualMetadata) -> Metadata:
    """The person's fields replace the text ones; series, volume and title (what Kavita groups by) stay."""
    if isinstance(metadata, ComicMetadata):
        return replace(metadata, localized_series=manual.localized_series, writers=manual.writers,
                       publisher=manual.publisher, release_date=manual.release_date or None,
                       genres=manual.genres, summary=manual.summary)
    return replace(metadata, authors=manual.writers, illustrators=manual.illustrators, publisher=manual.publisher,
                   date=manual.release_date,
                   genres=manual.genres, description=manual.summary)


def apply_subject(metadata: Metadata, subject: Subject) -> Metadata:
    """Everything a Bangumi subject knows, as organizing would have written it."""
    if isinstance(metadata, ComicMetadata):
        return replace(metadata, subject_id=comic_subject_id(subject), web_url=comic_web_url(subject),
                       localized_series=subject.display_title,
                       summary=subject.summary, writers=tuple(subject.writers), publisher=subject.publisher,
                       release_date=subject.release_date, genres=tuple(subject.genres),
                       completed=subject.completed, total_volumes=subject.total_volumes)
    return replace(metadata, authors=tuple(subject.writers), illustrators=tuple(subject.illustrators),
                   publisher=subject.publisher,
                   genres=select_genres(subject), description=" ".join(subject.summary.split()),
                   date=normalize_release_date(subject.release_date), web_url=subject.web_url)


def _staging(path: Path) -> Path:
    return path.with_name(".{0}.{1}.tmp".format(path.name, secrets.token_hex(4)))


def _swap(staged: Path, path: Path) -> None:
    try:
        shutil.copymode(path, staged)
    except OSError:
        pass
    os.replace(staged, path)


def rewrite_cbz(path: Path, metadata: ComicMetadata) -> None:
    """Swap the ComicInfo.xml of a CBZ; pages are copied unchanged. The original stays if anything fails."""
    path = Path(path)
    staged = _staging(path)
    try:
        with zipfile.ZipFile(path) as source:
            infos = [info for info in source.infolist() if info.filename.lower() != "comicinfo.xml"]
            pages = sum(1 for info in infos if not info.is_dir())
            with zipfile.ZipFile(staged, "x") as output:
                for info in infos:
                    with source.open(info) as reader, output.open(info, "w") as writer:
                        shutil.copyfileobj(reader, writer, 1024 * 1024)
                output.writestr("ComicInfo.xml", build_comic_info(metadata, pages), zipfile.ZIP_DEFLATED)
        verify_cbz(staged)
        _swap(staged, path)
    finally:
        if staged.exists():
            staged.unlink()


def rewrite_epub(path: Path, metadata: KavitaMetadata) -> None:
    """Rewrite the OPF metadata of an organized EPUB in place."""
    path = Path(path)
    staged = _staging(path)
    try:
        write_metadata(path, staged, metadata)
        _swap(staged, path)
    finally:
        if staged.exists():
            staged.unlink()
