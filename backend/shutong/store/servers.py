"""Media server connections (Kavita): one row each; the password is a secret the API never echoes."""
from dataclasses import dataclass
import sqlite3
from typing import List, Optional

from .db import Database
from .records import now_iso


@dataclass(frozen=True)
class ServerRecord:
    id: int
    kind: str
    name: str
    base_url: str
    username: str
    password: str
    enabled: bool


class ServerStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, kind: str, name: str, base_url: str, username: str, password: str) -> ServerRecord:
        with self.db.connect() as connection:
            server_id = connection.execute(
                "INSERT INTO media_servers(kind, name, base_url, username, password, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)", (kind, name, base_url, username, password, now_iso())).lastrowid
        return self.get(server_id)

    def get(self, server_id: int) -> ServerRecord:
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM media_servers WHERE id = ?", (server_id,)).fetchone()
        if row is None:
            raise KeyError(server_id)
        return _record(row)

    def all(self) -> List[ServerRecord]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM media_servers ORDER BY id").fetchall()
        return [_record(row) for row in rows]

    def update(self, server_id: int, *, name: Optional[str] = None, base_url: Optional[str] = None,
               username: Optional[str] = None, password: Optional[str] = None,
               enabled: Optional[bool] = None) -> ServerRecord:
        columns = {key: value for key, value in (("name", name), ("base_url", base_url), ("username", username),
                                                 ("password", password)) if value is not None}
        if enabled is not None:
            columns["enabled"] = int(enabled)
        if columns:
            assignments = ", ".join("{0} = ?".format(column) for column in columns)
            with self.db.connect() as connection:
                connection.execute("UPDATE media_servers SET {0} WHERE id = ?".format(assignments),
                                   (*columns.values(), server_id))
        return self.get(server_id)

    def delete(self, server_id: int) -> None:
        with self.db.connect() as connection:
            connection.execute("UPDATE libraries SET server_id = NULL, server_library_id = NULL"
                               " WHERE server_id = ?", (server_id,))
            connection.execute("DELETE FROM media_servers WHERE id = ?", (server_id,))


def _record(row: sqlite3.Row) -> ServerRecord:
    return ServerRecord(id=row["id"], kind=row["kind"], name=row["name"], base_url=row["base_url"],
                        username=row["username"], password=row["password"], enabled=bool(row["enabled"]))
