"""Publish journal: one row per in-flight publication, used for crash recovery."""
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Optional

from .db import Database
from .records import now_iso


@dataclass(frozen=True)
class JournalEntry:
    item_id: int
    staged_path: Path
    final_path: Path
    phase: str
    sha256: Optional[str]
    size: Optional[int]


class JournalStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def begin(self, item_id: int, staged: Path, final: Path) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO publish_journal(item_id, staged_path, final_path, phase,"
                " sha256, size, updated_at) VALUES (?, ?, ?, 'building', NULL, NULL, ?)",
                (item_id, str(staged), str(final), now_iso()),
            )

    def mark_staged(self, item_id: int, sha256: str, size: int) -> None:
        self._update(item_id, "phase = 'staged', sha256 = ?, size = ?", (sha256, size))

    def mark_published(self, item_id: int) -> None:
        self._update(item_id, "phase = 'published'", ())

    def delete(self, item_id: int) -> None:
        with self.db.connect() as connection:
            connection.execute("DELETE FROM publish_journal WHERE item_id = ?", (item_id,))

    def get(self, item_id: int) -> Optional[JournalEntry]:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM publish_journal WHERE item_id = ?", (item_id,)
            ).fetchone()
        return _entry(row) if row is not None else None

    def pending(self) -> list[JournalEntry]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM publish_journal WHERE phase != 'published' ORDER BY item_id"
            ).fetchall()
        return [_entry(row) for row in rows]

    def _update(self, item_id: int, assignments: str, values: tuple) -> None:
        with self.db.connect() as connection:
            cursor = connection.execute(
                "UPDATE publish_journal SET {0}, updated_at = ? WHERE item_id = ?".format(assignments),
                (*values, now_iso(), item_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(item_id)


def _entry(row: sqlite3.Row) -> JournalEntry:
    return JournalEntry(
        item_id=row["item_id"],
        staged_path=Path(row["staged_path"]),
        final_path=Path(row["final_path"]),
        phase=row["phase"],
        sha256=row["sha256"],
        size=row["size"],
    )
