"""What happens to a source after its output is published: keep, archive or delete."""
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import secrets
import shutil
from typing import Optional

from .fingerprint import fingerprint, sha256_file
from .publish import TargetExists, no_overwrite_move


@dataclass(frozen=True)
class DisposalContext:
    policy: str  # "keep" | "archive" | "delete"
    source_root: Path
    archive_dir: Optional[Path]


@dataclass(frozen=True)
class DisposalOutcome:
    outcome: str
    destination: Optional[Path] = None


def dispose_source(
    ctx: DisposalContext,
    source: Path,
    expected_fingerprint: str,
) -> DisposalOutcome:
    source = Path(source)
    if not os.path.lexists(source):
        return DisposalOutcome("source_missing")
    if fingerprint(source) != expected_fingerprint:
        return DisposalOutcome("source_changed")
    if ctx.policy == "keep":
        return DisposalOutcome("kept")
    if ctx.policy == "archive":
        if ctx.archive_dir is None:
            raise ValueError("archive policy needs an archive_dir")
        return _archive(source, Path(ctx.archive_dir) / _relative(ctx, source))
    if ctx.policy == "delete":
        remove_tree(source)
        return DisposalOutcome("deleted")
    raise ValueError("unknown source policy: {0}".format(ctx.policy))


def _relative(ctx: DisposalContext, source: Path) -> Path:
    try:
        return Path(os.path.abspath(source)).relative_to(os.path.abspath(ctx.source_root))
    except ValueError:
        return Path(source.name)


def _archive(source: Path, destination: Path) -> DisposalOutcome:
    if os.path.lexists(destination):
        return DisposalOutcome("archive_conflict")
    try:
        if _same_volume(source, destination):
            try:
                no_overwrite_move(source, destination)
                return DisposalOutcome("archived", destination)
            except TargetExists:
                raise
            except OSError as error:
                # Docker bind mounts of one host filesystem share st_dev but still
                # refuse link/rename across mount points.
                if error.errno != errno.EXDEV:
                    raise
        return _copy_then_delete(source, destination)
    except TargetExists:
        return DisposalOutcome("archive_conflict")


def _copy_then_delete(source: Path, destination: Path) -> DisposalOutcome:
    destination.parent.mkdir(parents=True, exist_ok=True)
    copy = destination.with_name(".{0}.{1}.copying".format(destination.name, secrets.token_hex(4)))
    try:
        if source.is_dir():
            shutil.copytree(source, copy)
        else:
            shutil.copy2(source, copy)
        if not _same_content(source, copy):
            remove_tree(copy)
            return DisposalOutcome("copy_mismatch")
        no_overwrite_move(copy, destination)
    except BaseException:
        remove_tree(copy)
        raise
    remove_tree(source)
    return DisposalOutcome("archived", destination)


def _same_content(source: Path, copy: Path) -> bool:
    if not source.is_dir():
        return sha256_file(source) == sha256_file(copy)
    originals = sorted(p.relative_to(source) for p in source.rglob("*") if p.is_file())
    copies = sorted(p.relative_to(copy) for p in copy.rglob("*") if p.is_file())
    if originals != copies:
        return False
    return all(sha256_file(source / name) == sha256_file(copy / name) for name in originals)


def _same_volume(a: Path, b: Path) -> bool:
    return os.stat(_existing_ancestor(a)).st_dev == os.stat(_existing_ancestor(b)).st_dev


def _existing_ancestor(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def remove_tree(path: Path) -> None:
    """Delete a file or a whole folder for good; a missing path is fine."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
