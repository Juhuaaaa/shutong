"""Files uploaded from the browser land in a library's source directory, under their relative path.

The first folder level is what recognition reads as the series folder, so a dropped folder
``迷宫饭/`` becomes ``<source>/迷宫饭/…``. Nothing is ever overwritten: a taken name gets ``-1``, ``-2``.
Hidden files (``.DS_Store`` and friends) are skipped; the scanner would ignore them anyway.
"""
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
from typing import BinaryIO, Optional

from shutong.engine.publish import TargetExists, no_overwrite_move
from shutong.engine.text import is_safe_path_component
from shutong.store.records import Library

_DRIVE = re.compile(r"^[A-Za-z]:")
_STATE_DIR = ".shutong"


def safe_relative(name: str) -> PurePosixPath:
    text = (name or "").replace("\\", "/")
    if not text.strip() or text.startswith("/") or _DRIVE.match(text):
        raise ValueError("不允许的文件路径：{0}".format(name))
    parts = [part for part in text.split("/") if part != ""]
    # casefold: macOS, Windows and SMB treat .Shutong and .shutong as the same folder.
    if not parts or any(not is_safe_path_component(part) or part.casefold().startswith(_STATE_DIR)
                        for part in parts):
        raise ValueError("不允许的文件路径：{0}".format(name))
    return PurePosixPath(*parts)


def is_hidden(relative: PurePosixPath) -> bool:
    return any(part.startswith(".") for part in relative.parts)


def save_upload(library: Library, name: str, stream: BinaryIO) -> Optional[PurePosixPath]:
    """Write one uploaded file; returns where it landed (relative to the source dir), None if skipped."""
    relative = safe_relative(name)
    if is_hidden(relative):
        return None
    root = Path(library.source_dir).resolve()
    target = root.joinpath(*relative.parts)
    _require_inside(root, target.parent)  # a symlinked folder must not lead outside the source dir
    target.parent.mkdir(parents=True, exist_ok=True)
    _require_inside(root, target.parent)
    # Short, hidden temp name: a long title plus ".part" could pass the 255-byte limit, and a leftover
    # from a killed process is ignored by the scanner.
    partial = target.parent / ".upload-{0}.part".format(secrets.token_hex(8))
    try:
        with open(partial, "xb") as handle:
            shutil.copyfileobj(stream, handle, 1024 * 1024)
        counter = 0
        while True:
            candidate = target if counter == 0 else target.with_name(
                "{0}-{1}{2}".format(target.stem, counter, target.suffix))
            try:
                no_overwrite_move(partial, candidate)
                return PurePosixPath(*candidate.relative_to(root).parts)
            except TargetExists:
                counter += 1
    finally:
        if partial.exists():
            partial.unlink()


def _require_inside(root: Path, directory: Path) -> None:
    existing = Path(directory)
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    real = Path(os.path.realpath(existing))
    if real != root and root not in real.parents:
        raise ValueError("不允许的文件路径：上传位置在来源目录外（{0}）".format(directory.relative_to(root)))
