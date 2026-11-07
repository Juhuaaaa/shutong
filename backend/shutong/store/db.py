"""SQLite access: one short-lived connection per unit of work."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator, Optional

from .migrations import MIGRATIONS

_BUSY_TIMEOUT_SECONDS = 10.0


class SchemaTooNew(RuntimeError):
    """The database was written by a newer version of the program."""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Commit on normal exit, roll back on error, always close."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, isolation_level=None, timeout=_BUSY_TIMEOUT_SECONDS)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            # IMMEDIATE takes the write lock up front: a deferred transaction that reads
            # first cannot upgrade once another writer commits (WAL SQLITE_BUSY_SNAPSHOT),
            # and that error bypasses the busy timeout.
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")
        finally:
            connection.close()

    def schema_version(self) -> int:
        with self.connect() as connection:
            return connection.execute("PRAGMA user_version").fetchone()[0]

    def check_compatible(self) -> None:
        if self.schema_version() > len(MIGRATIONS):
            raise SchemaTooNew("数据库版本 {0} 比程序支持的 {1} 新".format(self.schema_version(), len(MIGRATIONS)))

    def backup_before_upgrade(self) -> Optional[Path]:
        """A copy from before pending migrations, when there is anything to lose and to migrate."""
        version = self.schema_version()
        if version == 0 or version >= len(MIGRATIONS):
            return None
        target = self.path.with_name("{0}.bak-v{1}".format(self.path.name, version))
        source = sqlite3.connect(self.path)
        copy = sqlite3.connect(target)
        try:
            source.backup(copy)
        finally:
            copy.close()
            source.close()
        return target

    def migrate(self) -> None:
        """Apply pending scripts; each script and its version bump share one transaction."""
        current = self.schema_version()
        for version in range(current, len(MIGRATIONS)):
            with self.connect() as connection:
                for statement in _statements(MIGRATIONS[version]):
                    connection.execute(statement)
                connection.execute("PRAGMA user_version = {0}".format(version + 1))


def _statements(script: str) -> list[str]:
    # executescript() would commit our open transaction, so split and run one by one.
    statements, buffer = [], ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise ValueError("incomplete SQL statement in migration")
    return statements
