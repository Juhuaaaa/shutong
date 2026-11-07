"""Libraries, runs, items and the item event timeline."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Tuple
import unicodedata

from shutong.labels import note
from shutong.metadata.base import SubjectRef
from shutong.engine.states import ItemStatus, ReviewReason, check_transition

from .db import Database

_TRANSITION_FIELDS = frozenset({"parsed", "subject_id", "subject_source", "plan", "target_path", "error", "source_path", "group_key",
                                "source_root", "originals_kept"})
_JSON_FIELDS = frozenset({"parsed", "plan"})


KEEP = object()  # "leave this field as it is" for updates where None is a real value


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


@dataclass(frozen=True)
class Library:
    id: int
    name: str
    kind: str
    source_dir: Path
    library_dir: Path
    naming_template: str
    source_policy: str
    archive_dir: Optional[Path]
    pdf_to_cbz: bool
    server_id: Optional[int] = None  # media server notified after publishing
    server_library_id: Optional[str] = None  # that server's library id, as text
    include_edition: bool = True  # series names carry the edition (迷宫饭[bili电子版])
    # No source dir of its own: files only come in through uploads, kept under the data dir until organized.
    source_managed: bool = False
    watch: bool = False  # scan by itself once new files in the source dir have settled
    # When the volume is already in the library: never | always | larger (the bigger file stays) | newer.
    overwrite_policy: str = "never"
    rename_files: bool = True  # False: files keep their source name, only the folder comes from the template


@dataclass(frozen=True)
class Item:
    id: int
    library_id: int
    run_id: Optional[int]
    source_path: Path
    fingerprint: str
    status: ItemStatus
    review_reason: Optional[ReviewReason]
    parsed: dict
    subject_id: Optional[str]
    subject_source: Optional[str]
    plan: dict
    target_path: Optional[Path]
    error: Optional[str]
    created_at: str
    updated_at: str
    overrides: dict = None  # per-item choices from review, e.g. {"volume": "SP1"}
    group_key: Optional[str] = None  # the source folder a review or history record covers
    source_root: Optional[Path] = None  # set for files dropped in from elsewhere: relative paths start here
    originals_kept: bool = False  # the user chose to leave this dropped file's original alone

    @property
    def subject_ref(self) -> Optional[SubjectRef]:
        if not self.subject_id:
            return None
        return SubjectRef(self.subject_source or "bangumi", self.subject_id)


@dataclass(frozen=True)
class ItemEvent:
    id: int
    item_id: int
    at: str
    kind: str
    detail: dict


class LibraryStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        name: str,
        kind: str,
        source_dir: Path,
        library_dir: Path,
        *,
        source_policy: str = "keep",
        archive_dir: Optional[Path] = None,
        naming_template: str = "",
        pdf_to_cbz: bool = True,
        include_edition: bool = True,
        watch: bool = False,
        overwrite_policy: str = "never",
        rename_files: bool = True,
    ) -> Library:
        with self.db.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO libraries(name, kind, source_dir, library_dir, naming_template,"
                " source_policy, archive_dir, pdf_to_cbz, include_edition, watch, overwrite_policy, rename_files, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    name, kind, _source_column(source_dir), str(library_dir), naming_template,
                    source_policy, str(archive_dir) if archive_dir is not None else None,
                    int(pdf_to_cbz), int(include_edition), int(watch), overwrite_policy, int(rename_files), now_iso(),
                ),
            )
            library_id = cursor.lastrowid
        return self.get(library_id)

    def get(self, library_id: int) -> Library:
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM libraries WHERE id = ?", (library_id,)).fetchone()
        if row is None:
            raise KeyError(library_id)
        managed = row["source_dir"] == ""
        source_dir = self.uploads_dir(row["id"]) if managed else Path(row["source_dir"])
        if managed:
            source_dir.mkdir(parents=True, exist_ok=True)
        return Library(
            id=row["id"],
            name=row["name"],
            kind=row["kind"],
            source_dir=source_dir,
            source_managed=managed,
            watch=bool(row["watch"]),
            library_dir=Path(row["library_dir"]),
            naming_template=row["naming_template"],
            source_policy=row["source_policy"],
            archive_dir=Path(row["archive_dir"]) if row["archive_dir"] is not None else None,
            pdf_to_cbz=bool(row["pdf_to_cbz"]),
            server_id=row["server_id"],
            server_library_id=row["server_library_id"],
            include_edition=bool(row["include_edition"]),
            overwrite_policy=row["overwrite_policy"],
            rename_files=bool(row["rename_files"]),
        )


    def uploads_dir(self, library_id: int) -> Path:
        """Where uploads wait for a library without a source dir of its own."""
        return self.db.path.parent / "uploads" / str(library_id)

    def update(self, library_id: int, *, name: Optional[str] = None, naming_template: Optional[str] = None,
               source_policy: Optional[str] = None, archive_dir: Any = KEEP, pdf_to_cbz: Optional[bool] = None,
               source_dir: Any = None, library_dir: Optional[Path] = None,
               server_id: Any = KEEP, server_library_id: Any = KEEP,
               include_edition: Optional[bool] = None, watch: Optional[bool] = None,
               overwrite_policy: Optional[str] = None, rename_files: Optional[bool] = None) -> Library:
        """Change the given fields; ``archive_dir=None`` clears it, leaving it out keeps it.

        ``source_dir=""`` drops the library's own source dir (uploads only)."""
        columns = {}
        for column, value in (("name", name), ("naming_template", naming_template),
                              ("source_policy", source_policy), ("library_dir", library_dir)):
            if value is not None:
                columns[column] = str(value) if isinstance(value, Path) else value
        if source_dir is not None:
            columns["source_dir"] = _source_column(source_dir)
        if watch is not None:
            columns["watch"] = int(watch)
        if pdf_to_cbz is not None:
            columns["pdf_to_cbz"] = int(pdf_to_cbz)
        if include_edition is not None:
            columns["include_edition"] = int(include_edition)
        if overwrite_policy is not None:
            columns["overwrite_policy"] = overwrite_policy
        if rename_files is not None:
            columns["rename_files"] = int(rename_files)
        if archive_dir is not KEEP:
            columns["archive_dir"] = str(archive_dir) if archive_dir is not None else None
        if server_id is not KEEP:
            columns["server_id"] = server_id
        if server_library_id is not KEEP:
            columns["server_library_id"] = server_library_id
        if columns:
            assignments = ", ".join("{0} = ?".format(column) for column in columns)
            with self.db.connect() as connection:
                connection.execute("UPDATE libraries SET {0} WHERE id = ?".format(assignments),
                                   (*columns.values(), library_id))
        return self.get(library_id)

    def by_name(self, name: str) -> Library:
        with self.db.connect() as connection:
            row = connection.execute("SELECT id FROM libraries WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise KeyError(name)
        return self.get(row["id"])

    def all(self) -> List[Library]:
        with self.db.connect() as connection:
            ids = [row["id"] for row in connection.execute("SELECT id FROM libraries ORDER BY id")]
        return [self.get(library_id) for library_id in ids]


def _source_column(source_dir: Any) -> str:
    """"" (or None) stores a library without a source dir of its own."""
    if source_dir is None or (isinstance(source_dir, str) and not source_dir.strip()):
        return ""
    return str(source_dir)


class RunStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, library_id: int, trigger: str) -> int:
        with self.db.connect() as connection:
            return connection.execute(
                "INSERT INTO runs(library_id, trigger, started_at) VALUES (?, ?, ?)",
                (library_id, trigger, now_iso()),
            ).lastrowid

    def counts(self, run_id: int) -> dict:
        with self.db.connect() as connection:
            row = connection.execute("SELECT counts FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row["counts"])

    def finish(self, run_id: int, counts: dict) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE runs SET finished_at = ?, counts = ? WHERE id = ?",
                (now_iso(), _dumps(counts), run_id),
            )


class ItemStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self, library_id: int, source_path: Path, fingerprint: str, *, run_id: Optional[int] = None,
        group_key: Optional[str] = None, source_root: Optional[Path] = None,
    ) -> Item:
        stamp = now_iso()
        with self.db.connect() as connection:
            item_id = connection.execute(
                "INSERT INTO items(library_id, run_id, source_path, fingerprint, status, group_key,"
                " source_root, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (library_id, run_id, str(source_path), fingerprint,
                 ItemStatus.DISCOVERED.value, group_key, str(source_root) if source_root is not None else None,
                 stamp, stamp),
            ).lastrowid
            _insert_event(connection, item_id, "discovered", None)
        return self.get(item_id)

    def subject_sources_by_folder(self, library_id: int, root: Path) -> Dict[str, str]:
        """The metadata source each first-level folder under ``root`` was matched from, earliest item first."""
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT source_path, subject_source FROM items WHERE library_id = ? AND subject_source IS NOT NULL"
                " ORDER BY id", (library_id,)).fetchall()
        found: Dict[str, str] = {}
        for row in rows:
            try:
                parts = Path(row["source_path"]).relative_to(root).parts
            except ValueError:
                continue
            if len(parts) > 1:
                found.setdefault(unicodedata.normalize("NFC", parts[0]), row["subject_source"])
        return found

    def import_published(self, library_id: int, source_path: Path, fingerprint: str, target_path: Path, *,
                         parsed: dict, detail: dict) -> Item:
        """Record something organized before Shutong existed: straight to PUBLISHED, outside the state machine."""
        existing = self.find_by_fingerprint(library_id, fingerprint)
        if existing is not None:
            return existing
        stamp = now_iso()
        with self.db.connect() as connection:
            item_id = connection.execute(
                "INSERT INTO items(library_id, source_path, fingerprint, status, parsed, target_path,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (library_id, str(source_path), fingerprint, ItemStatus.PUBLISHED.value, _dumps(parsed),
                 str(target_path), stamp, stamp),
            ).lastrowid
            _insert_event(connection, item_id, "imported", detail)
        return self.get(item_id)

    def get(self, item_id: int) -> Item:
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(item_id)
        return _item(row)

    def list(self, library_id: int, status: Optional[ItemStatus] = None) -> List[Item]:
        query = "SELECT * FROM items WHERE library_id = ?"
        values: list = [library_id]
        if status is not None:
            query += " AND status = ?"
            values.append(status.value)
        with self.db.connect() as connection:
            rows = connection.execute(query + " ORDER BY id", values).fetchall()
        return [_item(row) for row in rows]

    def page(self, library_id: Optional[int], *, status: Optional[ItemStatus] = None,
             review_reason: Optional[ReviewReason] = None, query: Optional[str] = None,
             limit: int = 50, offset: int = 0) -> Tuple[List[Item], int]:
        """One page of items, newest first, and the total that match the filters."""
        conditions, values = [], []
        if library_id is not None:
            conditions.append("library_id = ?")
            values.append(library_id)
        if status is not None:
            conditions.append("status = ?")
            values.append(status.value)
        if review_reason is not None:
            conditions.append("review_reason = ?")
            values.append(review_reason.value)
        if query:
            conditions.append("(instr(lower(source_path), ?) > 0 OR instr(lower(coalesce(target_path, '')), ?) > 0)")
            values += [query.lower(), query.lower()]
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        with self.db.connect() as connection:
            total = connection.execute("SELECT count(*) FROM items" + where, values).fetchone()[0]
            rows = connection.execute("SELECT * FROM items" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
                                      (*values, limit, offset)).fetchall()
        return [_item(row) for row in rows], total

    def backfill_group_keys(self, resolver: Callable[[int, Path], str]) -> int:
        """Fill ``group_key`` for items stored before it existed; returns how many were filled."""
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT id, library_id, source_path FROM items WHERE group_key IS NULL").fetchall()
            connection.executemany("UPDATE items SET group_key = ? WHERE id = ?", [
                (resolver(row["library_id"], Path(row["source_path"])), row["id"]) for row in rows])
        return len(rows)

    def with_source_root(self) -> List[Item]:
        """Items dropped in from outside the library's source dir."""
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM items WHERE source_root IS NOT NULL ORDER BY id").fetchall()
        return [_item(row) for row in rows]

    def in_group(self, library_id: int, group_key: str) -> List[Item]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM items WHERE library_id = ? AND group_key = ? ORDER BY id",
                                      (library_id, group_key)).fetchall()
        return [_item(row) for row in rows]

    def group_page(self, library_id: Optional[int], *, status: Optional[ItemStatus] = None,
                   query: Optional[str] = None, missing_metadata: bool = False,
                   limit: int = 30, offset: int = 0) -> Tuple[List[dict], int]:
        """Items summed up per source folder, most recently updated first, and how many folders match.

        Missing metadata means organized without a Bangumi subject; review items have none yet and do not count.
        """
        where, values = "", []
        if library_id is not None:
            where, values = " WHERE library_id = ?", [library_id]
        having, having_values = [], []
        if status is not None:
            having.append("sum(status = ?) > 0")
            having_values.append(status.value)
        if query:
            having.append("(max(instr(lower(group_key), ?)) > 0"
                          " OR max(instr(lower(coalesce(json_extract(plan, '$.series'), '')), ?)) > 0)")
            having_values += [query.lower(), query.lower()]
        if missing_metadata:
            having.append("missing > 0")
        grouped = ("SELECT library_id, group_key, count(*) AS total, max(updated_at) AS updated_at,"
                   " sum(status = 'published' AND subject_id IS NULL"
                   " AND json_extract(overrides, '$.metadata') IS NULL) AS missing,"
                   " group_concat(id) AS ids FROM items" + where + " GROUP BY library_id, group_key"
                   + (" HAVING " + " AND ".join(having) if having else ""))
        with self.db.connect() as connection:
            total = connection.execute("SELECT count(*) FROM (" + grouped + ")",
                                       (*values, *having_values)).fetchone()[0]
            rows = connection.execute(grouped + " ORDER BY updated_at DESC, library_id, group_key LIMIT ? OFFSET ?",
                                      (*values, *having_values, limit, offset)).fetchall()
            groups = []
            for row in rows:
                ids = sorted(int(value) for value in row["ids"].split(","))
                counts = {status_row[0]: status_row[1] for status_row in connection.execute(
                    "SELECT status, count(*) FROM items WHERE library_id = ? AND group_key IS ? GROUP BY status",
                    (row["library_id"], row["group_key"]))}
                # Records imported from the old tool have no plan: the folder in the library names the series.
                named = connection.execute(
                    "SELECT coalesce(json_extract(plan, '$.series'), CASE WHEN instr(target_path, '/') > 1"
                    " THEN substr(target_path, 1, instr(target_path, '/') - 1) END) AS series, subject_id"
                    " FROM items WHERE library_id = ? AND group_key IS ?"
                    " AND (json_extract(plan, '$.series') IS NOT NULL OR subject_id IS NOT NULL"
                    " OR instr(target_path, '/') > 1)"
                    " ORDER BY status NOT IN ('planned', 'published'), id LIMIT 1",
                    (row["library_id"], row["group_key"])).fetchone()
                groups.append({"library_id": row["library_id"], "group_key": row["group_key"],
                               "folder": row["group_key"], "series": named[0] if named else None,
                               "subject_id": named[1] if named else None, "counts": counts,
                               "total": row["total"], "updated_at": row["updated_at"], "item_ids": ids,
                               "missing_metadata": row["missing"]})
        return groups, total

    def set_overrides(self, item_id: int, overrides: dict) -> None:
        with self.db.connect() as connection:
            connection.execute("UPDATE items SET overrides = ?, updated_at = ? WHERE id = ?",
                               (_dumps(overrides), now_iso(), item_id))

    def with_status(self, status: ItemStatus) -> List[Item]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM items WHERE status = ? ORDER BY id", (status.value,)).fetchall()
        return [_item(row) for row in rows]

    def find_by_fingerprint(self, library_id: int, fingerprint: str) -> Optional[Item]:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM items WHERE library_id = ? AND fingerprint = ?",
                (library_id, fingerprint),
            ).fetchone()
        return _item(row) if row is not None else None

    def published_owner(self, library_id: int, target: Path) -> Optional[int]:
        """The item a library file was first published from, if any."""
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT id FROM items WHERE library_id = ? AND target_path = ? AND status = ? ORDER BY id LIMIT 1",
                (library_id, str(target), ItemStatus.PUBLISHED.value),
            ).fetchone()
        return row[0] if row is not None else None

    def published_at(self, library_id: int, target: Path) -> List[int]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT id FROM items WHERE library_id = ? AND target_path = ? AND status = ? ORDER BY id",
                                      (library_id, str(target), ItemStatus.PUBLISHED.value)).fetchall()
        return [row[0] for row in rows]

    def published_volumes(self, library_id: int) -> Dict[Tuple[str, str], Path]:
        """Which file holds each volume of each series, by the records: file names need not say."""
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT json_extract(plan, '$.series'), json_extract(plan, '$.volume'), target_path FROM items"
                " WHERE library_id = ? AND status = ? AND target_path IS NOT NULL ORDER BY id",
                (library_id, ItemStatus.PUBLISHED.value)).fetchall()
        return {(row[0], row[1]): Path(row[2]) for row in rows if row[0] and row[1]}

    def transition(
        self,
        item_id: int,
        target: ItemStatus,
        *,
        event: str,
        detail: Optional[dict] = None,
        review_reason: Optional[ReviewReason] = None,
        **fields: Any,
    ) -> Item:
        unknown = set(fields) - _TRANSITION_FIELDS
        if unknown:
            raise TypeError("unknown item fields: {0}".format(", ".join(sorted(unknown))))
        if target is ItemStatus.NEEDS_REVIEW and review_reason is None:
            raise ValueError("needs_review requires a review_reason")
        if target is not ItemStatus.NEEDS_REVIEW:
            review_reason = None
        with self.db.connect() as connection:
            row = connection.execute("SELECT status FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise KeyError(item_id)
            check_transition(ItemStatus(row["status"]), target)
            columns = {"status": target.value, "review_reason": _enum_value(review_reason),
                       "updated_at": now_iso()}
            if target is not ItemStatus.FAILED:
                columns["error"] = None  # a retried item must not keep showing the old failure
            for name, value in fields.items():
                if name in _JSON_FIELDS:
                    value = _dumps(value)
                elif name in ("target_path", "source_path", "source_root") and value is not None:
                    value = str(value)
                columns[name] = value
            assignments = ", ".join("{0} = ?".format(name) for name in columns)
            connection.execute(
                "UPDATE items SET {0} WHERE id = ?".format(assignments),
                (*columns.values(), item_id),
            )
            _insert_event(connection, item_id, event, detail)
        item = self.get(item_id)
        _log_transition(item, event, detail)
        return item

    def update(self, item_id: int, *, event: str, detail: Optional[dict] = None, **fields: Any) -> Item:
        """Change data fields and log an event without a status transition."""
        unknown = set(fields) - _TRANSITION_FIELDS
        if unknown:
            raise TypeError("unknown item fields: {0}".format(", ".join(sorted(unknown))))
        with self.db.connect() as connection:
            columns = {"updated_at": now_iso()}
            for name, value in fields.items():
                if name in _JSON_FIELDS:
                    value = _dumps(value)
                elif name in ("target_path", "source_path", "source_root") and value is not None:
                    value = str(value)
                columns[name] = value
            assignments = ", ".join("{0} = ?".format(name) for name in columns)
            connection.execute("UPDATE items SET {0} WHERE id = ?".format(assignments),
                               (*columns.values(), item_id))
            _insert_event(connection, item_id, event, detail)
        return self.get(item_id)

    def add_event(self, item_id: int, kind: str, detail: Optional[dict] = None) -> None:
        with self.db.connect() as connection:
            _insert_event(connection, item_id, kind, detail)

    def events(self, item_id: int) -> List[ItemEvent]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM item_events WHERE item_id = ? ORDER BY at, id", (item_id,)
            ).fetchall()
        return [
            ItemEvent(id=row["id"], item_id=row["item_id"], at=row["at"], kind=row["kind"],
                      detail=json.loads(row["detail"]))
            for row in rows
        ]


_REASONS = {"naming": "命名不确定", "volume": "卷号不确定", "metadata": "无元数据匹配", "conflict": "冲突"}
log = logging.getLogger("shutong.items")


def _log_transition(item: "Item", event: str, detail: Optional[dict]) -> None:
    detail = detail or {}
    name = item.source_path.name
    extra = note(detail["note"]) if detail.get("note") else detail.get("error") or ""
    extra = "：{0}".format(extra) if extra else ""
    status = item.status
    if status is ItemStatus.NEEDS_REVIEW:
        reason = _REASONS.get(item.review_reason.value, item.review_reason.value) if item.review_reason else ""
        log.debug("进入复核（%s）：%s%s", reason, name, extra)  # thousands per scan: the job line has the count
    elif status is ItemStatus.PUBLISHED:
        log.info("已整理：%s → %s", name, item.target_path.as_posix() if item.target_path else "")
    elif status is ItemStatus.FAILED:
        log.error("失败：%s%s", name, extra)
    elif status is ItemStatus.DUPLICATE:
        log.info("判定为重复：%s%s", name, extra)
    elif status is ItemStatus.CANCELLED:
        log.info("已取消：%s", name)
    elif status is ItemStatus.PLANNED:
        log.debug("已规划：%s → %s", name, item.target_path.as_posix() if item.target_path else "")
    else:
        log.debug("%s：%s → %s", event, name, status.value)


def _enum_value(value: Optional[ReviewReason]) -> Optional[str]:
    return value.value if value is not None else None


def _insert_event(
    connection: sqlite3.Connection, item_id: int, kind: str, detail: Optional[dict]
) -> None:
    connection.execute(
        "INSERT INTO item_events(item_id, at, kind, detail) VALUES (?, ?, ?, ?)",
        (item_id, now_iso(), kind, _dumps(detail or {})),
    )


def _item(row: sqlite3.Row) -> Item:
    return Item(
        id=row["id"],
        library_id=row["library_id"],
        run_id=row["run_id"],
        source_path=Path(row["source_path"]),
        fingerprint=row["fingerprint"],
        status=ItemStatus(row["status"]),
        review_reason=ReviewReason(row["review_reason"]) if row["review_reason"] else None,
        parsed=json.loads(row["parsed"]),
        subject_id=None if row["subject_id"] is None else str(row["subject_id"]),
        subject_source=row["subject_source"],
        plan=json.loads(row["plan"]),
        target_path=Path(row["target_path"]) if row["target_path"] is not None else None,
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        overrides=json.loads(row["overrides"]),
        group_key=row["group_key"],
        source_root=Path(row["source_root"]) if row["source_root"] is not None else None,
        originals_kept=bool(row["originals_kept"]),
    )
