"""What every media-kind adapter (manga, novel) provides to the engine."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Tuple


class BuildError(ValueError):
    """A source could not be turned into a valid output file."""


@dataclass(frozen=True)
class SourceEntry:
    path: Path
    kind: str  # "archive" | "pdf" | "folder" (manga); adapters define their own kinds
    series_folder: Optional[str]  # first-level folder under the source dir, None for loose files
    root: Optional[Path] = None  # where relative names start, when it is not the library's source dir


@dataclass(frozen=True)
class Skipped:
    path: Path
    reason: str  # "symlink" | "unsupported"


@dataclass(frozen=True)
class ScanResult:
    entries: Tuple[SourceEntry, ...]
    skipped: Tuple[Skipped, ...]


@dataclass(frozen=True)
class ParseResult:
    """What recognition settled for one source."""

    title_hint: str
    edition: Optional[str]
    volume: Any  # the kind's volume type, e.g. VolumeRef for manga; None when unknown
    details: Mapping[str, Any] = field(default_factory=dict)  # kind-specific facts, e.g. EPUB OPF title
    search_titles: Tuple[str, ...] = ()  # other names to search the metadata source with


class KindAdapter(Protocol):
    kind: str

    def scan(self, source_dir: Path) -> ScanResult: ...

    def file_kind(self, path: Path) -> Optional[str]:
        """The entry kind of a single file, None if this library cannot organize it."""
        ...

    def folder_kind(self, path: Path) -> Optional[str]:
        """The entry kind of a folder that is one book by itself, None if it is not."""
        ...

    def facts(self, entry: SourceEntry) -> Mapping[str, Any]: ...

    def volume_from_ai(self, reading: Any) -> Any: ...

    def build(self, entry: SourceEntry, metadata: Any, staged: Path) -> int: ...

    def verify(self, staged: Path, metadata: Any) -> None: ...
