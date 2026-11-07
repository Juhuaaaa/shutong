"""Manga kind adapter: archives, PDFs and image folders in, ComicInfo CBZ out."""
import os
from pathlib import Path
import shutil
import tempfile
from typing import List, Optional
from xml.etree import ElementTree
import zipfile

from shutong.engine.kinds.base import BuildError, ScanResult, Skipped, SourceEntry

from .cbz import ArchiveLimits, collect_archive_pages, image_extension, verify_cbz, write_cbz
from .comicinfo import ComicMetadata, _format_decimal, build_comic_info, read_comic_info
from .comicinfo import chapter_number as _chapter_number
from .folder import collect_folder_pages
from .naming import build_archive_name
from .pdf import collect_pdf_pages, pdf_page_count
from .volume import VolumeRef

ARCHIVE_SUFFIXES = frozenset({".zip", ".cbz", ".rar", ".cbr", ".7z", ".cb7"})
PDF_SUFFIX = ".pdf"
_SNIFF_BYTES = 32


def default_relative_target(
    series_name: str, volume: VolumeRef, width: int = 2, suffix: str = ".cbz"
) -> Path:
    """``<series>/<series> Vol.NN.cbz`` — the legacy library layout."""
    name = build_archive_name(series_name, volume, width)
    return Path(series_name) / (name[: -len(".cbz")] + suffix)


class MangaAdapter:
    kind = "manga"

    def __init__(self, limits: ArchiveLimits = ArchiveLimits(), pdf_to_cbz: bool = True) -> None:
        self.limits = limits
        self.pdf_to_cbz = pdf_to_cbz

    def output_suffix(self, entry: SourceEntry) -> str:
        return ".pdf" if self._keeps_pdf(entry) else ".cbz"

    def _keeps_pdf(self, entry: SourceEntry) -> bool:
        return entry.kind == "pdf" and not self.pdf_to_cbz

    def file_kind(self, path: Path) -> Optional[str]:
        suffix = Path(path).suffix.casefold()
        return "archive" if suffix in ARCHIVE_SUFFIXES else "pdf" if suffix == PDF_SUFFIX else None

    def folder_kind(self, path: Path) -> Optional[str]:
        children = sorted(child for child in Path(path).iterdir() if not child.name.startswith("."))
        if any(child.is_dir() for child in children):
            return None
        return "folder" if any(_is_image(child) for child in children) else None

    def scan(self, source_dir: Path) -> ScanResult:
        source_dir = Path(source_dir)
        entries: List[SourceEntry] = []
        skipped: List[Skipped] = []
        for current, directories, files in os.walk(source_dir, followlinks=False):
            current_path = Path(current)
            for name in list(directories):
                if (current_path / name).is_symlink():
                    skipped.append(Skipped(current_path / name, "symlink"))
            directories[:] = sorted(
                name for name in directories
                if not name.startswith(".") and not (current_path / name).is_symlink()
            )
            visible = sorted(name for name in files if not name.startswith("."))
            sources = []
            has_image = False
            for name in visible:
                path = current_path / name
                if path.is_symlink():
                    skipped.append(Skipped(path, "symlink"))
                    continue
                suffix = path.suffix.casefold()
                if suffix in ARCHIVE_SUFFIXES:
                    sources.append(SourceEntry(path, "archive", _series_folder(source_dir, path)))
                elif suffix == PDF_SUFFIX:
                    sources.append(SourceEntry(path, "pdf", _series_folder(source_dir, path)))
                elif not has_image and _is_image(path):
                    has_image = True
            if current_path != source_dir and has_image and not sources and not directories:
                entries.append(SourceEntry(current_path, "folder", _series_folder(source_dir, current_path)))
            entries.extend(sources)
        entries.sort(key=lambda entry: entry.path.relative_to(source_dir).as_posix())
        skipped.sort(key=lambda item: item.path.as_posix())
        return ScanResult(tuple(entries), tuple(skipped))

    def facts(self, entry: SourceEntry) -> dict:
        """What the file itself says about its series; manga sources carry nothing worth sending."""
        return {}

    def volume_from_ai(self, reading) -> Optional[VolumeRef]:
        """An :class:`~shutong.engine.ai_recognize.FileReading` as a volume; None when it has no number."""
        if reading.unit == "special":
            number = int(reading.number) if reading.number is not None and reading.number >= 1 else 1
            return VolumeRef.special(number, reading.label)
        if reading.number is None:
            return None
        if reading.unit == "chapter":
            return VolumeRef.chapter(reading.number, reading.end)
        if reading.end is not None and reading.end > reading.number:
            return VolumeRef.range(reading.number, reading.end)
        return VolumeRef.volume(reading.number)

    def build(self, entry: SourceEntry, metadata: ComicMetadata, staged: Path) -> int:
        staged = Path(staged)
        if os.path.lexists(staged):
            raise BuildError("staged path already exists: {0}".format(staged))
        try:
            if self._keeps_pdf(entry):
                pages = pdf_page_count(entry.path)
                shutil.copyfile(entry.path, staged)
                return pages
            with tempfile.TemporaryDirectory(prefix="shutong-manga-") as work:
                if entry.kind == "archive":
                    pages = collect_archive_pages(entry.path, Path(work), self.limits)
                elif entry.kind == "pdf":
                    pages = collect_pdf_pages(entry.path, Path(work))
                elif entry.kind == "folder":
                    pages = collect_folder_pages(entry.path)
                else:
                    raise BuildError("unknown manga source kind: {0}".format(entry.kind))
                write_cbz(pages, build_comic_info(metadata, len(pages)), staged)
            return len(pages)
        except BaseException as error:
            # Never leave a partial output at the staged path.
            try:
                staged.unlink()
            except FileNotFoundError:
                pass
            if isinstance(error, BuildError) or not isinstance(error, Exception):
                raise
            raise BuildError(str(error)) from error

    def verify(self, staged: Path, metadata: ComicMetadata) -> None:
        if Path(staged).suffix.casefold() == PDF_SUFFIX:
            # A kept PDF carries no ComicInfo; the folder and file name hold series and volume.
            pdf_page_count(staged)
            return
        try:
            verify_cbz(staged, self.limits)
            fields = read_comic_info(staged)
        except (ValueError, OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
            raise BuildError("output CBZ failed verification: {0}".format(error)) from error
        if fields.get("Series") != metadata.series_name:
            raise BuildError("ComicInfo Series does not match the plan")
        for tag, expected in _volume_fields(metadata.volume).items():
            if fields.get(tag) != expected:
                raise BuildError("ComicInfo {0} does not match the plan".format(tag))


def _volume_fields(volume: VolumeRef) -> dict:
    """The volume tags build_comic_info writes; absent tags are expected to be absent."""
    if volume.kind == "special":
        return {"Number": "SP{0:02d}".format(volume.special_number), "Format": "Special",
                "Volume": None}
    if volume.kind == "range":
        return {"Volume": "{0}-{1}".format(_format_decimal(volume.start), _format_decimal(volume.end)),
                "Number": None}
    if volume.kind == "chapter":
        return {"Number": _chapter_number(volume), "Volume": None}
    return {"Volume": _format_decimal(volume.start), "Number": None}


def _series_folder(source_dir: Path, path: Path):
    parts = path.relative_to(source_dir).parts
    return parts[0] if len(parts) > 1 else None


def _is_image(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return image_extension(handle.read(_SNIFF_BYTES)) is not None
    except OSError:
        return False
