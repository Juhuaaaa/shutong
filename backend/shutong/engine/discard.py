"""Removing a file the user may want back: into the system trash on the desktop, gone for good on a server.

A server (Docker) has no trash anyone would look in; the desktop does, and its users expect deleted files there.
Where the trash is not available (some network drives), the file is deleted as on a server.
"""
import logging
import os
from pathlib import Path
import shutil
from typing import Callable, Optional

log = logging.getLogger("shutong.discard")

_trash: Optional[Callable[[str], None]] = None


def use_system_trash(on: bool, *, trasher: Optional[Callable[[str], None]] = None) -> None:
    """Called once at startup: the desktop app turns the trash on."""
    global _trash
    if not on:
        _trash = None
        return
    if trasher is None:
        from send2trash import send2trash as trasher  # only the desktop needs it
    _trash = trasher


def trash_enabled() -> bool:
    return _trash is not None


def discard(path: Path) -> str:
    """``trashed``, ``deleted`` or ``missing``."""
    path = Path(path)
    if not os.path.lexists(path):
        return "missing"
    if _trash is not None:
        try:
            _trash(str(path))
            return "trashed"
        except Exception as error:  # no trash on that drive, say: do what a server would
            log.warning("移进回收站失败，直接删除：%s（%s）", path, error)
    remove_for_good(path)
    return "deleted"


def remove_for_good(path: Path) -> None:
    """Delete a file or a whole folder; a missing path is fine."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
