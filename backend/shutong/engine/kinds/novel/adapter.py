"""Light novel kind adapter: EPUB in, EPUB with Kavita series metadata out."""
from dataclasses import dataclass
import os
from pathlib import Path
from typing import List, Optional
import unicodedata
import zipfile

from shutong.engine.kinds.base import BuildError, ScanResult, Skipped, SourceEntry

from .epub import KavitaMetadata, read_metadata, spine_length, validate_package, write_metadata
from .naming import NovelVolume, natural_key, target_filename

EPUB_SUFFIX = ".epub"


@dataclass(frozen=True)
class NovelPlan:
    """What build/verify need: the source (to compare members) and the OPF metadata to write."""

    source: Path
    metadata: KavitaMetadata


def default_relative_target(
    output_name: str,
    volume: NovelVolume,
    width: int = 2,
    special_index: Optional[int] = None,
) -> Path:
    return Path(output_name) / target_filename(output_name, volume, width, special_index)


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


class NovelAdapter:
    kind = "novel"

    def file_kind(self, path: Path) -> Optional[str]:
        return "epub" if Path(path).suffix.casefold() == EPUB_SUFFIX else None

    def folder_kind(self, path: Path) -> Optional[str]:
        return None

    def scan(self, source_dir: Path) -> ScanResult:
        source_dir = Path(source_dir)
        entries: List[SourceEntry] = []
        skipped: List[Skipped] = []
        for current, directories, files in os.walk(source_dir, followlinks=False):
            current_path = Path(current)
            for name in list(directories):
                if (current_path / name).is_symlink():
                    skipped.append(Skipped(current_path / name, "symlink"))
            directories[:] = [
                name for name in directories
                if not name.startswith(".") and not (current_path / name).is_symlink()
            ]
            for name in files:
                if name.startswith(".") or name.startswith("~$"):
                    continue
                path = current_path / name
                if path.is_symlink():
                    skipped.append(Skipped(path, "symlink"))
                    continue
                if path.suffix.casefold() != EPUB_SUFFIX:
                    continue
                parts = path.relative_to(source_dir).parts
                folder = _nfc(parts[0]) if len(parts) > 1 else None
                entries.append(SourceEntry(path, "epub", folder))
        entries.sort(key=lambda entry: natural_key(_nfc(entry.path.relative_to(source_dir).as_posix())))
        skipped.sort(key=lambda item: item.path.as_posix())
        return ScanResult(tuple(entries), tuple(skipped))

    def facts(self, entry: SourceEntry) -> dict:
        """The EPUB's own title and authors help the AI; a damaged file just has none."""
        try:
            metadata = read_metadata(entry.path)
        except Exception:
            return {}
        return {"title": metadata.title, "creators": metadata.creators,
                "publisher": metadata.publisher, "languages": metadata.languages}

    def volume_from_ai(self, reading) -> Optional[NovelVolume]:
        if reading.unit == "special":
            return NovelVolume.special()
        if reading.number is None or (reading.end is not None and reading.end != reading.number):
            return None  # novels have no merged volumes: let a person decide
        return NovelVolume.volume(reading.number)

    def build(self, entry: SourceEntry, plan: NovelPlan, staged: Path) -> int:
        staged = Path(staged)
        if os.path.lexists(staged):
            raise BuildError("staged path already exists: {0}".format(staged))
        try:
            write_metadata(plan.source, staged, plan.metadata)
            return spine_length(staged)
        except BaseException as error:
            try:
                staged.unlink()
            except FileNotFoundError:
                pass
            if isinstance(error, BuildError) or not isinstance(error, Exception):
                raise
            raise BuildError(str(error)) from error

    def verify(self, staged: Path, plan: NovelPlan) -> None:
        try:
            self._verify(Path(staged), plan)
        except BuildError:
            raise
        except Exception as error:  # zlib.error, RuntimeError, ... from a damaged output
            raise BuildError("output EPUB failed verification: {0}".format(error)) from error

    def _verify(self, staged: Path, plan: NovelPlan) -> None:
        expected = plan.metadata
        metadata = read_metadata(staged)
        if metadata.series != expected.series:
            raise BuildError("series metadata was not written")
        if metadata.series_index != str(expected.series_index):
            raise BuildError("series index metadata was not written")
        if metadata.title != expected.title:
            raise BuildError("title metadata was not written")
        if not metadata.languages or metadata.languages[0] != expected.language:
            raise BuildError("language metadata was not written")
        with zipfile.ZipFile(plan.source) as source_archive:
            source_entries = set(source_archive.namelist())
        with zipfile.ZipFile(staged) as output_archive:
            infos = output_archive.infolist()
            names = [info.filename for info in infos]
            if "mimetype" in names:
                if names[0] != "mimetype":
                    raise BuildError("mimetype must be the first EPUB member")
                if infos[0].compress_type != zipfile.ZIP_STORED:
                    raise BuildError("mimetype must be stored uncompressed")
        if set(names) != source_entries:
            raise BuildError("EPUB member list changed during rewrite")
        problems = validate_package(staged)
        if problems:
            raise BuildError("EPUB manifest is not Kavita-compatible: {0}".format("; ".join(problems)))
