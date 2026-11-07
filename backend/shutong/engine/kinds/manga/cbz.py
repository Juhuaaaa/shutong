"""Safe archive page collection, CBZ writing, and verification.

Copied from the legacy shutong.core.manga.archive; publication moved to the engine Publisher.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from typing import BinaryIO, List, Optional, Sequence, Tuple, Union
import warnings
from xml.etree import ElementTree
import zipfile

from shutong.engine.kinds.base import BuildError

_CHUNK_SIZE = 1024 * 1024
_NUMBER_PARTS = re.compile(r"(\d+)")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_PAGE_NAME = re.compile(r"^[0-9]{3,}\.(jpg|png|gif|webp|avif)$")
_ZIP_SUFFIXES = {".zip", ".cbz"}
_NON_ZIP_SUFFIXES = {".rar", ".cbr", ".7z", ".cb7"}


ArchiveSource = Union[int, BinaryIO]


@dataclass(frozen=True)
class ArchiveLimits:
    # Long-strip webtoon packs run to ~10 000 images (dozens per chapter); they are packed page for page.
    max_files: int = 30000
    max_total_bytes: int = 8 * 1024**3
    max_file_bytes: int = 512 * 1024**2
    # Comic archives legitimately contain near-uniform pages (blank backs, solid
    # colour plates, placeholder covers) that compress far better than ordinary
    # artwork: a valid 2144x3204 JPEG cover was observed at ~212x. Real
    # decompression bombs are three or more orders of magnitude beyond that, so
    # this threshold stays well clear of genuine images while `max_file_bytes`
    # and `max_total_bytes` remain the primary guard against expansion.
    max_compression_ratio: int = 1000


@dataclass(frozen=True)
class ArchiveReport:
    page_count: int
    uncompressed_bytes: int


@dataclass(frozen=True)
class Page:
    name: str
    extension: str
    path: Path


@dataclass(frozen=True)
class _ListedEntry:
    archive_name: str
    normalized_name: str
    is_directory: bool
    declared_size: int


def _natural_key(value: str):
    return [int(part) if part.isdigit() else part.casefold() for part in _NUMBER_PARTS.split(value)]


def _validate_limits(limits: ArchiveLimits) -> None:
    values = (
        limits.max_files,
        limits.max_total_bytes,
        limits.max_file_bytes,
        limits.max_compression_ratio,
    )
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in values):
        raise ValueError("archive limits must be positive integers")


def _validate_archive_path(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        "\x00" in name
        or normalized.startswith("/")
        or _WINDOWS_DRIVE.match(normalized)
        or path.is_absolute()
        or ".." in path.parts
    ):
        raise ValueError("unsafe archive path: {0}".format(name))
    return path.as_posix()


def _validate_zip_info(info: zipfile.ZipInfo) -> bool:
    _validate_archive_path(info.orig_filename)
    _validate_archive_path(info.filename)
    name_is_directory = info.filename.endswith("/")
    if info.create_system == 3:
        file_type = stat.S_IFMT(info.external_attr >> 16)
        if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError("archive link or special entry is not allowed: {0}".format(info.filename))
        if file_type == stat.S_IFDIR and not name_is_directory:
            raise ValueError("archive directory mode requires a directory name: {0}".format(info.filename))
        if file_type == stat.S_IFREG and name_is_directory:
            raise ValueError("archive directory name has regular-file mode: {0}".format(info.filename))
    return name_is_directory


def _check_declared_size(info: zipfile.ZipInfo, limits: ArchiveLimits, total: int) -> None:
    if info.file_size > limits.max_file_bytes:
        raise ValueError("archive file size limit exceeded: {0}".format(info.filename))
    if total + info.file_size > limits.max_total_bytes:
        raise ValueError("archive total size limit exceeded")
    if info.file_size:
        if info.compress_size == 0 or info.file_size > info.compress_size * limits.max_compression_ratio:
            raise ValueError("archive compression ratio limit exceeded: {0}".format(info.filename))


def _copy_limited(
    source: BinaryIO,
    destination: Optional[BinaryIO],
    name: str,
    limits: ArchiveLimits,
    total_before: int,
    compressed_size: Optional[int],
    ratio_bytes_before: int = 0,
) -> Tuple[int, bytes]:
    size = 0
    prefix = bytearray()
    while True:
        allowed = min(
            limits.max_file_bytes - size,
            limits.max_total_bytes - total_before - size,
        )
        if compressed_size is not None:
            allowed = min(
                allowed,
                compressed_size * limits.max_compression_ratio - ratio_bytes_before - size,
            )
        chunk = source.read(min(_CHUNK_SIZE, max(0, allowed) + 1))
        if not chunk:
            break
        size += len(chunk)
        if size > limits.max_file_bytes:
            raise ValueError("archive file size limit exceeded: {0}".format(name))
        if total_before + size > limits.max_total_bytes:
            raise ValueError("archive total size limit exceeded")
        if size and compressed_size is not None:
            if compressed_size == 0 or ratio_bytes_before + size > compressed_size * limits.max_compression_ratio:
                raise ValueError("archive compression ratio limit exceeded: {0}".format(name))
        if len(prefix) < 32:
            prefix.extend(chunk[: 32 - len(prefix)])
        if destination is not None:
            destination.write(chunk)
    return size, bytes(prefix)


def image_extension(data: bytes) -> Optional[str]:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) >= 16 and data[4:8] == b"ftyp":
        brands = [data[8:12]] + [data[index : index + 4] for index in range(16, len(data) - 3, 4)]
        if b"avif" in brands or b"avis" in brands:
            return ".avif"
    return None


def _open_archive_source(
    source: Path, source_file: Optional[ArchiveSource]
) -> Tuple[BinaryIO, bool]:
    if source_file is None:
        return source.open("rb"), True
    if isinstance(source_file, bool):
        raise TypeError("archive source descriptor must be an integer or binary file")
    if isinstance(source_file, int):
        return os.fdopen(os.dup(source_file), "rb"), True
    if not hasattr(source_file, "read") or not hasattr(source_file, "seek"):
        raise TypeError("archive source descriptor must be an integer or binary file")
    return source_file, False


def _archive_suffix(source: Path, archive_suffix: Optional[str]) -> str:
    suffix = source.suffix if archive_suffix is None else archive_suffix
    if not isinstance(suffix, str) or not suffix:
        raise ValueError("archive suffix must be a non-empty string")
    suffix = suffix.casefold()
    if not suffix.startswith("."):
        suffix = "." + suffix
    return suffix


def _collect_zip(
    source: Path,
    destination: Path,
    limits: ArchiveLimits,
    source_file: Optional[ArchiveSource] = None,
) -> Tuple[List[Page], int]:
    pages = []
    total = 0
    file_count = 0
    archive_source, close_source = _open_archive_source(source, source_file)
    try:
        archive_source.seek(0)
        with zipfile.ZipFile(archive_source) as archive:
            for index, info in enumerate(archive.infolist()):
                if _validate_zip_info(info):
                    continue
                file_count += 1
                if file_count > limits.max_files:
                    raise ValueError("archive contains too many files")
                _check_declared_size(info, limits, total)
                spool = destination / "entry-{0}".format(index)
                with archive.open(info) as input_file, spool.open("wb") as output_file:
                    size, prefix = _copy_limited(
                        input_file,
                        output_file,
                        info.filename,
                        limits,
                        total,
                        info.compress_size,
                    )
                total += size
                extension = image_extension(prefix)
                if extension is None:
                    spool.unlink()
                else:
                    pages.append(Page(info.filename, extension, spool))
    finally:
        if close_source:
            archive_source.close()
    pages.sort(key=lambda page: _natural_key(page.name))
    return pages, total


# On Windows bsdtar's arguments go through the system code page (迷宫饭 arrives as ???) and every build of it
# crashes on non-ASCII member names. The library's wide-character API has neither problem.
_USE_LIBARCHIVE = os.name == "nt"


def _run_bsdtar(arguments: List[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(arguments, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "bsdtar failed")
    return result


def _snapshot_source(
    source: Path,
    destination: Path,
    limits: ArchiveLimits,
    source_file: Optional[ArchiveSource] = None,
    archive_suffix: Optional[str] = None,
) -> Path:
    snapshot = destination / ("source" + _archive_suffix(source, archive_suffix))
    input_file, close_source = _open_archive_source(source, source_file)
    try:
        input_file.seek(0)
        before = os.fstat(input_file.fileno())
        if before.st_size > limits.max_total_bytes:
            raise ValueError("archive snapshot size limit exceeded")
        with snapshot.open("xb") as output_file:
            copied = 0
            copied_digest = hashlib.sha256()
            while True:
                remaining = limits.max_total_bytes - copied
                chunk = input_file.read(min(_CHUNK_SIZE, remaining + 1))
                if not chunk:
                    break
                copied += len(chunk)
                if copied > limits.max_total_bytes:
                    raise ValueError("archive snapshot size limit exceeded")
                output_file.write(chunk)
                copied_digest.update(chunk)
            output_file.flush()
        input_file.seek(0)
        checked = 0
        checked_digest = hashlib.sha256()
        while True:
            remaining = limits.max_total_bytes - checked
            chunk = input_file.read(min(_CHUNK_SIZE, remaining + 1))
            if not chunk:
                break
            checked += len(chunk)
            if checked > limits.max_total_bytes:
                raise ValueError("archive snapshot size limit exceeded")
            checked_digest.update(chunk)
        after = os.fstat(input_file.fileno())
    except BaseException:
        try:
            snapshot.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        if close_source:
            input_file.close()
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if (
        identity_before != identity_after
        or copied != before.st_size
        or copied_digest.digest() != checked_digest.digest()
    ):
        raise ValueError("source archive changed while being snapshotted")
    return snapshot


class _Blocks:
    """``read(size)`` over libarchive's blocks of one entry."""

    def __init__(self, blocks) -> None:
        self._blocks = iter(blocks)
        self._held = b""

    def read(self, size: int = -1) -> bytes:
        parts = [self._held]
        held = len(self._held)
        while size < 0 or held < size:
            block = next(self._blocks, None)
            if block is None:
                break
            parts.append(bytes(block))
            held += len(block)
        data = b"".join(parts)
        if size < 0:
            self._held = b""
            return data
        self._held = data[size:]
        return data[:size]


def _libarchive_reader(archive: Path):
    try:
        import libarchive
    except Exception as error:  # not installed, or its DLL did not load
        raise BuildError("rar/7z support needs libarchive: {0}".format(error)) from error
    return libarchive.file_reader(str(archive))


def _plain_entry(entry) -> bool:
    return (entry.isreg or entry.isdir) and not (entry.issym or entry.islnk)


def _list_with_libarchive(source: Path, limits: ArchiveLimits) -> List[_ListedEntry]:
    entries: List[_ListedEntry] = []
    seen_names = set()
    declared_total = 0
    with _libarchive_reader(source) as archive:
        for entry in archive:
            if len(entries) >= limits.max_files:
                raise ValueError("archive contains too many files")
            name = entry.pathname
            normalized = _validate_archive_path(name)
            if normalized.casefold() in seen_names:
                raise ValueError("duplicate archive path: {0}".format(name))
            seen_names.add(normalized.casefold())
            if not _plain_entry(entry):
                raise ValueError("archive link or special entry is not allowed")
            size = 0 if entry.isdir else entry.size
            if size is None or size < 0:
                raise ValueError("could not safely inspect archive entry sizes")
            if size > limits.max_file_bytes:
                raise ValueError("archive file size limit exceeded")
            declared_total += size
            if declared_total > limits.max_total_bytes:
                raise ValueError("archive total size limit exceeded")
            entries.append(_ListedEntry(name, normalized, bool(entry.isdir), size))
    compressed_size = source.stat().st_size
    if declared_total and (compressed_size == 0 or declared_total > compressed_size * limits.max_compression_ratio):
        raise ValueError("archive compression ratio limit exceeded")
    return entries


def _archive_names(source: Path) -> List[str]:
    """Every name in the archive, links too: for the packaging smoke test, nothing here is extracted."""
    if not _USE_LIBARCHIVE:
        return [name for name in _run_bsdtar([_bsdtar(), "-tf", str(source)]).stdout.splitlines() if name]
    with _libarchive_reader(source) as archive:
        return [entry.pathname for entry in archive]


def _list_non_zip(source: Path, limits: ArchiveLimits) -> List[_ListedEntry]:
    if _USE_LIBARCHIVE:
        return _list_with_libarchive(source, limits)
    names_result = _run_bsdtar([_bsdtar(), "-tf", str(source)])
    names = [name for name in names_result.stdout.splitlines() if name]
    if len(names) > limits.max_files:
        raise ValueError("archive contains too many files")

    normalized_names = []
    seen_names = set()
    for name in names:
        normalized = _validate_archive_path(name)
        folded = normalized.casefold()
        if folded in seen_names:
            raise ValueError("duplicate archive path: {0}".format(name))
        seen_names.add(folded)
        normalized_names.append(normalized)

    verbose_result = _run_bsdtar([_bsdtar(), "-tvf", str(source)])
    verbose_lines = [line for line in verbose_result.stdout.splitlines() if line]
    if len(verbose_lines) != len(names):
        raise ValueError("could not safely inspect archive entry types")

    entries = []
    declared_total = 0
    for name, normalized, line in zip(names, normalized_names, verbose_lines):
        if line[0] not in ("-", "d") or " link to " in line or " -> " in line:
            raise ValueError("archive link or special entry is not allowed")
        fields = line.split()
        try:
            declared_size = int(fields[4])
        except (IndexError, ValueError) as error:
            raise ValueError("could not safely inspect archive entry sizes") from error
        is_directory = line[0] == "d"
        if is_directory:
            declared_size = 0
        if declared_size < 0 or declared_size > limits.max_file_bytes:
            raise ValueError("archive file size limit exceeded")
        declared_total += declared_size
        if declared_total > limits.max_total_bytes:
            raise ValueError("archive total size limit exceeded")
        entries.append(_ListedEntry(name, normalized, is_directory, declared_size))

    compressed_size = source.stat().st_size
    if declared_total and (
        compressed_size == 0 or declared_total > compressed_size * limits.max_compression_ratio
    ):
        raise ValueError("archive compression ratio limit exceeded")
    return entries


def _collect_non_zip(
    source: Path,
    destination: Path,
    limits: ArchiveLimits,
    source_file: Optional[ArchiveSource] = None,
    archive_suffix: Optional[str] = None,
) -> Tuple[List[Page], int]:
    if source_file is not None:
        # A caller-held descriptor may not match the path any more: read a private copy.
        archive = _snapshot_source(source, destination, limits, source_file, archive_suffix)
        before = None
    else:
        # Read in place: copying the whole archive first cost seconds per volume. A source
        # replaced or rewritten while it is read is caught by its identity afterwards.
        archive = source
        before = _identity(source)
        if before[2] > limits.max_total_bytes:
            raise ValueError("archive size limit exceeded")
    pages, total = _extract_non_zip(archive, destination, limits)
    if before is not None and _identity(source) != before:
        raise ValueError("source archive changed while being read")
    return pages, total


def _identity(path: Path) -> Tuple[int, int, int, int]:
    info = os.stat(path)
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _take_from_bsdtar(archive: Path, take) -> None:
    with tempfile.TemporaryFile() as error_file:
        process = subprocess.Popen(
            [_bsdtar(), "-cf", "-", "--format", "pax", "@" + str(archive)],
            stdout=subprocess.PIPE,
            stderr=error_file,
        )
        if process.stdout is None:
            process.kill()
            process.wait()
            raise RuntimeError("bsdtar did not provide an output stream")
        try:
            try:
                with tarfile.open(fileobj=process.stdout, mode="r|", encoding="utf-8",
                                  errors="surrogateescape") as stream:
                    for index, member in enumerate(stream):
                        take(index, member.name, member.isreg(), member.isdir(), member.size,
                             lambda: stream.extractfile(member))
            finally:
                process.stdout.close()
            return_code = process.wait()
        except BaseException:
            process.kill()
            process.wait()
            raise
        if return_code:
            error_file.seek(0)
            message = error_file.read(8192).decode("utf-8", "replace").strip()
            raise RuntimeError(message or "bsdtar could not read the archive")


def _extract_non_zip(archive: Path, destination: Path, limits: ArchiveLimits) -> Tuple[List[Page], int]:
    """Read every page of a rar/7z in one pass.

    bsdtar re-encodes the archive as a tar stream on stdout (on Windows the library hands the entries over
    directly); asking for one member at a time made it decompress a solid rar from the start for every
    page. Each streamed entry must match the pre-listing (same path, regular file, same size) before a byte of it is copied.
    """
    entries = _list_non_zip(archive, limits)
    expected = {entry.normalized_name: entry for entry in entries if not entry.is_directory}
    compressed_size = archive.stat().st_size
    pages = []
    total = 0

    def take(index: int, name: str, regular: bool, directory: bool, size: int, open_reader) -> None:
        nonlocal total
        normalized = _validate_archive_path(name)
        if not (regular or directory):
            raise ValueError("archive link or special entry is not allowed")
        if directory:
            return
        entry = expected.pop(normalized, None)
        if entry is None:
            raise ValueError("archive member is not in the listing: {0}".format(name))
        if size != entry.declared_size:
            raise ValueError("archive member size does not match listing: {0}".format(name))
        path = destination / "entry-{0}".format(index)
        with path.open("xb") as output_file:
            copied, prefix = _copy_limited(open_reader(), output_file, name, limits, total,
                                           compressed_size, ratio_bytes_before=total)
        if copied != entry.declared_size:
            raise ValueError("archive member size does not match listing: {0}".format(name))
        total += copied
        extension = image_extension(prefix)
        if extension is None:
            path.unlink()
        else:
            pages.append(Page(normalized, extension, path))

    if _USE_LIBARCHIVE:
        with _libarchive_reader(archive) as reader:
            for index, member in enumerate(reader):
                take(index, member.pathname, _plain_entry(member) and not member.isdir, bool(member.isdir),
                     member.size, lambda: _Blocks(member.get_blocks()))
    else:
        _take_from_bsdtar(archive, take)
    if expected:
        raise ValueError("archive member is missing from the archive: {0}".format(next(iter(expected))))
    pages.sort(key=lambda page: _natural_key(page.name))
    return pages, total


def _collect_archive(
    source: Path,
    destination: Path,
    limits: ArchiveLimits,
    source_file: Optional[ArchiveSource] = None,
    archive_suffix: Optional[str] = None,
) -> Tuple[List[Page], int]:
    suffix = _archive_suffix(source, archive_suffix)
    if suffix in _ZIP_SUFFIXES:
        return _collect_zip(source, destination, limits, source_file)
    if suffix in _NON_ZIP_SUFFIXES:
        return _collect_non_zip(
            source, destination, limits, source_file, suffix
        )
    raise ValueError("unsupported archive type: {0}".format(suffix))


def inspect_archive(
    source: Path,
    limits: ArchiveLimits = ArchiveLimits(),
    *,
    source_file: Optional[ArchiveSource] = None,
    archive_suffix: Optional[str] = None,
) -> ArchiveReport:
    source = Path(source)
    _validate_limits(limits)
    with tempfile.TemporaryDirectory(prefix="manga-archive-inspect-") as directory:
        pages, total = _collect_archive(
            source, Path(directory), limits, source_file, archive_suffix
        )
        if not pages:
            raise ValueError("archive contains no valid images")
        return ArchiveReport(len(pages), total)


def _parse_comic_info(comic_info: bytes) -> None:
    try:
        ElementTree.fromstring(comic_info)
    except (ElementTree.ParseError, TypeError) as error:
        raise ValueError("invalid ComicInfo.xml") from error


def _warn_safely(message: str) -> None:
    try:
        warnings.warn(message, RuntimeWarning)
    except Exception:
        pass


def verify_cbz(path: Path, limits: ArchiveLimits = ArchiveLimits()) -> ArchiveReport:
    _validate_limits(limits)
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > limits.max_files:
            raise ValueError("archive contains too many files")

        directory_entries = []
        for info in infos:
            if _validate_zip_info(info):
                directory_entries.append(info)
        folded_names = [info.filename.casefold() for info in infos]
        metadata = [info for info in infos if info.filename.casefold().endswith("comicinfo.xml")]
        if len(metadata) != 1 or metadata[0].filename != "ComicInfo.xml" or folded_names.count("comicinfo.xml") != 1:
            raise ValueError("CBZ must contain exactly one root ComicInfo.xml")
        if len(folded_names) != len(set(folded_names)):
            raise ValueError("CBZ contains duplicate case-variant names")
        if directory_entries:
            raise ValueError("CBZ must not contain directory entries")

        total = 0
        page_count = 0
        for info in infos:
            _check_declared_size(info, limits, total)
            with archive.open(info) as input_file:
                size, prefix = _copy_limited(
                    input_file,
                    None,
                    info.filename,
                    limits,
                    total,
                    info.compress_size,
                )
            total += size
            if info.filename == "ComicInfo.xml":
                try:
                    _parse_comic_info(archive.read(info))
                except ValueError as error:
                    raise ValueError("invalid ComicInfo.xml") from error
                continue
            if "/" in info.filename or "\\" in info.filename or not _PAGE_NAME.fullmatch(info.filename):
                raise ValueError("unsafe CBZ page name: {0}".format(info.filename))
            extension = image_extension(prefix)
            if extension is None:
                raise ValueError("invalid CBZ page: {0}".format(info.filename))
            if not info.filename.endswith(extension):
                raise ValueError("CBZ page extension does not match content: {0}".format(info.filename))
            page_count += 1

        if page_count == 0:
            raise ValueError("CBZ contains no valid images")
        # Every member was read to its end above, which is where zipfile checks the CRC:
        # a testzip() pass would only read the whole archive a second time.
        return ArchiveReport(page_count, total)


def _bsdtar() -> str:
    """bsdtar reads rar/7z; the desktop app brings its own, Windows 10+ ships one as tar.exe."""
    bundled = os.environ.get("SHUTONG_BSDTAR")
    if bundled:
        return bundled
    if shutil.which("bsdtar"):
        return "bsdtar"
    if os.name == "nt" and shutil.which("tar"):
        return "tar"
    raise BuildError("rar/7z support needs bsdtar")


def collect_archive_pages(
    source: Path, workdir: Path, limits: ArchiveLimits = ArchiveLimits()
) -> List[Page]:
    """Extract the image pages of a zip/cbz/rar/cbr/7z/cb7 into ``workdir``, in reading order."""
    _validate_limits(limits)
    try:
        pages, _ = _collect_archive(Path(source), Path(workdir), limits)
    except BuildError:
        raise
    except (ValueError, RuntimeError, OSError, zipfile.BadZipFile, NotImplementedError) as error:
        raise BuildError(str(error)) from error
    if not pages:
        raise BuildError("archive contains no valid images")
    return pages


def write_cbz(pages: Sequence[Page], comic_info: bytes, target: Path) -> ArchiveReport:
    """Write pages as 001.jpg… plus a root ComicInfo.xml; no target is left on failure.

    Pages are stored as they are (images do not compress further) and the publisher verifies
    the result before it is moved into the library, so it is not read back here.
    """
    target = Path(target)
    _parse_comic_info(comic_info)
    if not pages:
        raise BuildError("no pages to write")
    if os.path.lexists(str(target)):
        raise FileExistsError("target already exists: {0}".format(target))
    width = max(3, len(str(len(pages))))
    try:
        total = 0
        with open(target, "xb") as handle, zipfile.ZipFile(
            handle, "w", compression=zipfile.ZIP_STORED
        ) as output:
            for number, page in enumerate(pages, start=1):
                output.write(page.path, "{0:0{1}d}{2}".format(number, width, page.extension))
                total += os.path.getsize(page.path)
            output.writestr("ComicInfo.xml", comic_info, zipfile.ZIP_DEFLATED)
        return ArchiveReport(len(pages), total + len(comic_info))
    except BaseException:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        raise
