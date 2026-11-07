"""Cheap identity for source files: size plus the first and last MiB.

mtime is deliberately ignored — copies and SMB mounts rewrite it.
"""
import hashlib
from pathlib import Path

_EDGE = 1024 * 1024


def fingerprint(path: Path) -> str:
    path = Path(path)
    if path.is_dir():
        return "v1:d:" + _directory_digest(path)
    return "v1:f:" + _file_digest(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_EDGE), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_digest(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha256(str(size).encode("ascii") + b"\0")
    with open(path, "rb") as handle:
        if size <= 2 * _EDGE:
            digest.update(handle.read())
        else:
            digest.update(handle.read(_EDGE))
            handle.seek(-_EDGE, 2)
            digest.update(handle.read(_EDGE))
    return digest.hexdigest()


def _directory_digest(root: Path) -> str:
    entries = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts) or not path.is_file():
            continue
        entries.append((relative.as_posix(), path.stat().st_size))
    digest = hashlib.sha256()
    for name, size in sorted(entries):
        digest.update("{0}\0{1}\n".format(name, size).encode("utf-8"))
    return digest.hexdigest()
