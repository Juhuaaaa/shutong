"""Fingerprints remembered by path, size and modified time, so a scan reads only new or changed files.

Only scans use it, to tell known files at a glance. Anything that removes or replaces a source still reads the file
itself: a wrong guess there would cost the user a file, here it costs one more read.
"""
import os
from pathlib import Path
from typing import Iterable, Optional

from .db import Database


class FingerprintCache:
    def __init__(self, db: Database) -> None:
        self.db = db

    def lookup(self, path: Path, size: int, mtime_ns: int) -> Optional[str]:
        with self.db.connect() as connection:
            row = connection.execute("SELECT fingerprint FROM fingerprint_cache WHERE path = ? AND size = ? AND mtime_ns = ?",
                                     (str(path), size, mtime_ns)).fetchone()
        return row[0] if row else None

    def remember(self, path: Path, size: int, mtime_ns: int, fingerprint: str) -> None:
        with self.db.connect() as connection:
            connection.execute("INSERT OR REPLACE INTO fingerprint_cache(path, size, mtime_ns, fingerprint) VALUES (?, ?, ?, ?)",
                               (str(path), size, mtime_ns, fingerprint))

    def forget_except(self, root: Path, kept: Iterable[Path]) -> int:
        """Drop what was remembered under ``root`` for files a full scan of it no longer found."""
        keep = {str(path) for path in kept}
        prefix = str(root).rstrip("/\\") + os.sep
        with self.db.connect() as connection:
            stale = [row[0] for row in connection.execute(
                "SELECT path FROM fingerprint_cache WHERE substr(path, 1, ?) = ?", (len(prefix), prefix))
                if row[0] not in keep]
            connection.executemany("DELETE FROM fingerprint_cache WHERE path = ?", [(path,) for path in stale])
        return len(stale)
