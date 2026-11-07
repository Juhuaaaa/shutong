"""The home page: per-library numbers, recently organized folders, jobs and disk space."""
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from shutong.api.auth import require_login
from shutong.api.routes.jobs import JobOut
from shutong.api.schemas import cover_url
from shutong.store.records import LibraryStore

router = APIRouter(prefix="/api", tags=["dashboard"], dependencies=[Depends(require_login)])
_RECENT = 8
_JOBS = 5


class LibraryStats(BaseModel):
    id: int
    name: str
    kind: str
    series: int
    volumes: int
    month_new: int
    planned: int
    needs_review: int
    failed: int
    available: bool


class RecentGroup(BaseModel):
    library_id: int
    group_key: str
    series: Optional[str]
    subject_id: Optional[str]
    subject_source: Optional[str]
    image: Optional[str]
    published: int
    at: str


class Storage(BaseModel):
    path: str
    total: int
    used: int
    free: int


class Dashboard(BaseModel):
    libraries: List[LibraryStats]
    recent: List[RecentGroup]
    jobs: List[JobOut]
    storage: List[Storage]


@router.get("/dashboard", response_model=Dashboard)
def dashboard(request: Request) -> dict:
    db = request.app.state.db
    month = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    libraries, storage, devices = [], [], set()
    stored = LibraryStore(db).all()
    # File system first: a stale network mount can stall a stat, and a connection holds the write lock.
    disk = {}
    for library in stored:
        available = Path(library.source_dir).is_dir() and Path(library.library_dir).is_dir()
        disk[library.id] = (available, _series_count(library.library_dir) if available else 0)
        if Path(library.library_dir).is_dir():
            _add_storage(storage, devices, library.library_dir)
    with db.connect() as connection:
        for library in stored:
            counts = dict(connection.execute(
                "SELECT status, count(*) FROM items WHERE library_id = ? GROUP BY status", (library.id,)).fetchall())
            month_new = connection.execute(
                "SELECT count(DISTINCT e.item_id) FROM item_events e JOIN items i ON i.id = e.item_id"
                " WHERE i.library_id = ? AND i.status = 'published' AND e.kind = 'published' AND e.at >= ?",
                (library.id, month)).fetchone()[0]
            available, series = disk[library.id]
            libraries.append({
                "id": library.id, "name": library.name, "kind": library.kind, "series": series,
                "volumes": counts.get("published", 0), "month_new": month_new,
                "planned": counts.get("planned", 0), "needs_review": counts.get("needs_review", 0),
                "failed": counts.get("failed", 0), "available": available,
            })
        recent = [_recent(connection, row) for row in connection.execute(
            "SELECT i.library_id, i.group_key, max(e.at) AS at FROM item_events e JOIN items i ON i.id = e.item_id"
            " WHERE e.kind = 'published' AND i.group_key IS NOT NULL GROUP BY i.library_id, i.group_key"
            " ORDER BY at DESC LIMIT ?", (_RECENT,)).fetchall()]
    jobs = [job.public() for job in request.app.state.jobs.recent(_JOBS)]
    return {"libraries": libraries, "recent": recent, "jobs": jobs, "storage": storage}


def _series_count(library_dir: Path) -> int:
    try:
        return sum(1 for entry in os.scandir(library_dir) if entry.is_dir() and not entry.name.startswith("."))
    except OSError:
        return 0


def _add_storage(storage: list, devices: set, directory: Path) -> None:
    try:
        device = os.stat(directory).st_dev
        usage = shutil.disk_usage(directory)
    except OSError:
        return
    if device in devices:
        return
    devices.add(device)
    storage.append({"path": str(directory), "total": usage.total, "used": usage.used, "free": usage.free})


def _recent(connection, row) -> dict:
    published, series = connection.execute(
        "SELECT count(*), max(json_extract(plan, '$.series')) FROM items"
        " WHERE library_id = ? AND group_key = ? AND status = 'published'",
        (row["library_id"], row["group_key"])).fetchone()
    named = connection.execute(
        "SELECT subject_id, coalesce(subject_source, 'bangumi') FROM items WHERE library_id = ? AND group_key = ?"
        " AND status = 'published' AND subject_id IS NOT NULL ORDER BY id DESC LIMIT 1",
        (row["library_id"], row["group_key"])).fetchone()
    subject_id, source = (named[0], named[1]) if named else (None, None)
    return {"library_id": row["library_id"], "group_key": row["group_key"], "series": series,
            "subject_id": subject_id, "subject_source": source, "image": cover_url(source, subject_id),
            "published": published, "at": row["at"]}
