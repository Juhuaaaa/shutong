"""Turn paths dropped on the desktop window into scan entries, without looking at anything else around them.

Each entry gets a root, the folder its relative names start at, and that decides what the AI reads as the
series folder. See :func:`_root_of_folder`.
"""
from dataclasses import dataclass, replace
import os
from pathlib import Path
from typing import List, Sequence, Set, Tuple
import unicodedata

from .kinds.base import KindAdapter, Skipped, SourceEntry


@dataclass(frozen=True)
class DropResult:
    entries: Tuple[SourceEntry, ...]
    skipped: Tuple[Skipped, ...]  # reason: "unsupported" | "empty" | "missing" | "symlink"
    rejected: Tuple[Path, ...]  # overlaps the library itself


def resolve_drops(adapter: KindAdapter, paths: Sequence[Path], library_dir: Path) -> DropResult:
    entries: List[SourceEntry] = []
    skipped: List[Skipped] = []
    rejected: List[Path] = []
    seen: Set[Path] = set()

    def add(entry: SourceEntry) -> None:
        if entry.path not in seen:
            seen.add(entry.path)
            entries.append(entry)

    for path in map(Path, paths):
        if not os.path.lexists(path):
            skipped.append(Skipped(path, "missing"))
        elif _overlaps(path, Path(library_dir)):
            rejected.append(path)
        elif path.is_symlink():
            skipped.append(Skipped(path, "symlink"))
        elif path.is_dir():
            found = _from_folder(adapter, path)
            skipped.extend(found.skipped)
            for entry in found.entries:
                add(entry)
            if not found.entries:
                skipped.append(Skipped(path, "empty"))
        else:
            kind = None if path.name.startswith(".") else adapter.file_kind(path)
            if kind is None:
                skipped.append(Skipped(path, "unsupported"))
            else:
                add(SourceEntry(path, kind, _loose_folder(path), path.parent))
    return DropResult(tuple(entries), tuple(skipped), tuple(rejected))


def _from_folder(adapter: KindAdapter, folder: Path) -> DropResult:
    scan = adapter.scan(folder)
    if not scan.entries:
        kind = adapter.folder_kind(folder)
        entries = (SourceEntry(folder, kind, _loose_folder(folder), folder.parent),) if kind is not None else ()
        return DropResult(entries, scan.skipped, ())
    root = _root_of_folder(folder, scan.entries)
    return DropResult(tuple(replace(entry, root=root, series_folder=_series_folder(root, entry.path))
                            for entry in scan.entries), scan.skipped, ())


def _loose_folder(path: Path):
    return unicodedata.normalize("NFC", path.parent.name) if path.parent.name else None


def _root_of_folder(folder: Path, entries: Sequence[SourceEntry]) -> Path:
    """A folder holding volumes (files, or image folders one level down) is the series: its parent is the root.
    One holding more in its subfolders is a collection, each subfolder a series of its own, whatever stray file
    lies next to them: the folder itself is the root."""
    volumes = sum(entry.path.parent == folder for entry in entries)
    return folder.parent if volumes and volumes >= len(entries) - volumes else folder


def _series_folder(root: Path, path: Path):
    parts = path.relative_to(root).parts
    return unicodedata.normalize("NFC", parts[0]) if len(parts) > 1 else None


def _overlaps(path: Path, library_dir: Path) -> bool:
    real = Path(os.path.realpath(path))
    library = Path(os.path.realpath(library_dir))
    return real == library or library in real.parents or real in library.parents
