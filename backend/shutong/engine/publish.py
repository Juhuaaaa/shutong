"""Portable publication: build in staging on the target volume, verify, then move
into place; an existing entry is only ever replaced when the caller says so."""
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import shutil
from typing import Callable

from shutong.store.journal import JournalStore

from .discard import discard, trash_enabled
from .fingerprint import sha256_file

STATE_DIR = ".shutong"
_ILLEGAL_CHARS = frozenset('<>:"/\\|?*')
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {"COM{0}".format(n) for n in range(1, 10)}
    | {"LPT{0}".format(n) for n in range(1, 10)}
)
# Windows refuses longer paths unless the machine was set up otherwise.
_MAX_PATH = 259 if os.name == "nt" else None


class TargetExists(FileExistsError):
    pass


class InvalidTargetName(ValueError):
    pass


@dataclass(frozen=True)
class PublishResult:
    final_path: Path
    sha256: str
    size: int
    method: str


@dataclass(frozen=True)
class RecoveryOutcome:
    item_id: int
    outcome: str  # "published" | "reset" | "conflict"


def validate_target(library_dir: Path, final: Path) -> None:
    """Refuse targets outside the library, inside our state dir, or illegal on Windows."""
    root = Path(os.path.abspath(library_dir))
    target = Path(os.path.abspath(final))
    try:
        parts = target.relative_to(root).parts
    except ValueError:
        raise InvalidTargetName("{0} is outside the library".format(final)) from None
    if not parts:
        raise InvalidTargetName("target is the library root")
    if parts[0] == STATE_DIR:
        raise InvalidTargetName("target is inside {0}".format(STATE_DIR))
    if _MAX_PATH is not None and len(str(target)) > _MAX_PATH:
        raise InvalidTargetName("库目录太深或书名太长，路径超过了系统限制：请把库目录换到浅一点的位置")
    # Validate the caller's components, not the normalized ones: on Windows abspath()
    # silently strips trailing dots and spaces, hiding exactly the names we must refuse.
    raw = Path(final).parts
    for part in raw[len(raw) - len(parts):]:
        _validate_component(part)


def _validate_component(part: str) -> None:
    if not part or part in {".", ".."}:
        raise InvalidTargetName("empty path component")
    if any(char in _ILLEGAL_CHARS or ord(char) < 32 for char in part):
        raise InvalidTargetName("illegal character in {0!r}".format(part))
    if part[-1] in {".", " "}:
        raise InvalidTargetName("{0!r} ends with a dot or space".format(part))
    if part.split(".", 1)[0].upper() in _RESERVED:
        raise InvalidTargetName("{0!r} is a reserved name".format(part))


def no_overwrite_move(src: Path, dst: Path) -> str:
    """Move ``src`` to ``dst``; raise TargetExists rather than replace anything."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        try:
            os.rename(src, dst)  # fails when dst exists
        except FileExistsError:
            raise TargetExists(str(dst)) from None
        return "rename"
    if not src.is_dir():
        try:
            os.link(src, dst)
        except FileExistsError:
            raise TargetExists(str(dst)) from None
        except OSError:
            pass  # no hard links here (some SMB/exFAT mounts)
        else:
            os.unlink(src)
            return "link"
    # Directories and link-less filesystems: check-then-rename leaves a small race window.
    if os.path.lexists(dst):
        raise TargetExists(str(dst))
    os.rename(src, dst)
    return "fallback"


class Publisher:
    def __init__(self, journal: JournalStore) -> None:
        self.journal = journal

    def staging_path(self, library_dir: Path, item_id: int, suffix: str) -> Path:
        directory = Path(library_dir) / STATE_DIR / "staging"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / "{0}-{1}{2}".format(item_id, secrets.token_hex(4), suffix)

    def start(self, item_id: int, library_dir: Path, final: Path, *, overwrite: bool = False) -> Path:
        validate_target(library_dir, final)
        if not overwrite and os.path.lexists(final):
            raise TargetExists(str(final))
        staged = self.staging_path(library_dir, item_id, Path(final).suffix)
        self.journal.begin(item_id, staged, Path(final))
        return staged

    def commit(self, item_id: int, verify: Callable[[Path], None], *, overwrite: bool = False) -> PublishResult:
        """``overwrite`` atomically takes the place of what is at the target: only after the new file verified."""
        entry = self.journal.get(item_id)
        if entry is None:
            raise KeyError(item_id)
        staged, final = entry.staged_path, entry.final_path
        try:
            _fsync(staged)
            verify(staged)
            digest = sha256_file(staged)
            size = staged.stat().st_size
            self.journal.mark_staged(item_id, digest, size)
            if overwrite:
                final.parent.mkdir(parents=True, exist_ok=True)
                if trash_enabled():
                    discard(final)  # the replaced file goes to the trash on the desktop
                os.replace(staged, final)
                method = "replace"
            else:
                method = no_overwrite_move(staged, final)
        except BaseException as error:
            if isinstance(error, Exception):
                self.abort(item_id)
            raise  # a simulated kill (BaseException) leaves state for recovery
        self.journal.mark_published(item_id)
        return PublishResult(final_path=final, sha256=digest, size=size, method=method)

    def recover(self) -> list["RecoveryOutcome"]:
        """Settle publications interrupted by a crash; never touches a foreign target."""
        outcomes = []
        for entry in self.journal.pending():
            final = entry.final_path
            # staged files live in <library>/.shutong/staging: no library dir means an unmounted share,
            # and "target missing" would be a lie. Leave the entry for the next start.
            if not Path(entry.staged_path).parent.parent.parent.is_dir():
                continue
            if os.path.lexists(final):
                ours = (
                    entry.phase == "staged"
                    and final.is_file()
                    and sha256_file(final) == entry.sha256
                )
                _remove(entry.staged_path)
                if ours:
                    self.journal.mark_published(entry.item_id)
                    outcome = "published"
                else:
                    self.journal.delete(entry.item_id)
                    outcome = "conflict"
            else:
                _remove(entry.staged_path)
                self.journal.delete(entry.item_id)
                outcome = "reset"
            outcomes.append(RecoveryOutcome(item_id=entry.item_id, outcome=outcome))
        return outcomes

    def sweep_staging(self, library_dir: Path) -> int:
        """Delete staging leftovers that no pending publication owns."""
        directory = Path(library_dir) / STATE_DIR / "staging"
        if not directory.is_dir():
            return 0
        owned = {os.path.normcase(str(entry.staged_path)) for entry in self.journal.pending()}
        removed = 0
        for path in directory.iterdir():
            if os.path.normcase(str(path)) not in owned:
                _remove(path)
                removed += 1
        return removed

    def abort(self, item_id: int) -> None:
        entry = self.journal.get(item_id)
        if entry is None:
            return
        _remove(entry.staged_path)
        self.journal.delete(item_id)


def _fsync(path: Path) -> None:
    with open(path, "rb+") as handle:
        os.fsync(handle.fileno())


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
