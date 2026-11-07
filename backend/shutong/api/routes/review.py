import json
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from shutong.api.auth import require_login
from shutong.api.routes.items import auto_execute, check_choices, planned_ids, require_ai, submit
from shutong.api.schemas import JobRef, ReviewGroup, SubjectRefIn, ref_out
from shutong.engine.organizer import Organizer, review_group
from shutong.engine.states import ItemStatus, ReviewReason
from shutong.store.records import ItemStore, LibraryStore

router = APIRouter(prefix="/api/review", tags=["review"], dependencies=[Depends(require_login)])


class Confirm(BaseModel):
    item_ids: List[int]
    title: Optional[str] = None
    edition: Optional[str] = None
    subject: Optional[SubjectRefIn] = None
    volumes: Dict[int, str] = {}
    skip_metadata: bool = False  # organize under the title without a metadata subject


class Reidentify(BaseModel):
    item_ids: Optional[List[int]] = None
    library_id: Optional[int] = None


@router.get("/groups", response_model=List[ReviewGroup])
def groups(request: Request, library_id: Optional[int] = None, reason: Optional[ReviewReason] = None) -> List[dict]:
    """Items waiting for review, one group per source folder; a fixed handful of queries in one connection."""
    db = request.app.state.db
    conditions, values = ["status = ?"], [ItemStatus.NEEDS_REVIEW.value]
    if library_id is not None:
        conditions.append("library_id = ?")
        values.append(library_id)
    if reason is not None:
        conditions.append("review_reason = ?")
        values.append(reason.value)
    with db.connect() as connection:
        rows = connection.execute("SELECT id, library_id, group_key, source_path, review_reason FROM items WHERE "
                                  + " AND ".join(conditions) + " ORDER BY id", values).fetchall()
    found = _group_rows(db, rows)  # may look a library up: outside the connection, which holds the write lock
    firsts = [group["first"] for group in found.values()]
    parsed, events = {}, {}
    with db.connect() as connection:
        for start in range(0, len(firsts), 500):  # stay under SQLite's variable limit
            chunk = firsts[start:start + 500]
            marks = ",".join("?" * len(chunk))
            for row in connection.execute("SELECT id, parsed FROM items WHERE id IN ({0})".format(marks), chunk):
                parsed[row["id"]] = json.loads(row["parsed"])
            for row in connection.execute(
                    "SELECT item_id, kind, detail FROM item_events WHERE kind IN ('review', 'ai_suggestion')"
                    " AND item_id IN ({0}) ORDER BY id DESC".format(marks), chunk):
                events.setdefault(row["item_id"], []).append((row["kind"], json.loads(row["detail"] or "{}")))
    for group in found.values():
        first = group.pop("first")
        info = parsed.get(first, {})
        group.update(title_hint=info.get("title_hint") or "", edition=info.get("edition"),
                     candidates=[], ai_suggestion=None)
        for kind, detail in events.get(first, []):  # newest first
            if kind == "review" and not group["candidates"]:
                refs = [ref_out(value) for value in detail.get("candidates") or []]
                group["candidates"] = [ref for ref in refs if ref is not None]
            if kind == "ai_suggestion" and group["ai_suggestion"] is None:
                group["ai_suggestion"] = detail
    return sorted(found.values(), key=lambda group: (-group["count"], group["folder"]))


def _group_rows(db, rows) -> Dict[str, dict]:
    libraries: Dict[int, object] = {}
    found: Dict[str, dict] = {}
    for row in rows:
        folder = row["group_key"]
        if folder is None:  # only before the startup backfill ran
            library = libraries.get(row["library_id"])
            if library is None:
                library = libraries[row["library_id"]] = LibraryStore(db).get(row["library_id"])
            folder = review_group(library, Path(row["source_path"]))
        key = "{0}:{1}".format(row["library_id"], folder)
        group = found.get(key)
        if group is None:
            group = found[key] = {"key": key, "library_id": row["library_id"], "folder": folder, "reasons": [],
                                  "count": 0, "item_ids": [], "sample_names": [], "first": row["id"]}
        group["count"] += 1
        group["item_ids"].append(row["id"])
        if row["review_reason"] and row["review_reason"] not in group["reasons"]:
            group["reasons"].append(row["review_reason"])
        if len(group["sample_names"]) < 5:
            group["sample_names"].append(Path(row["source_path"]).name)
    return found


@router.post("/confirm", response_model=JobRef)
def confirm(body: Confirm, request: Request) -> JobRef:
    ids = list(dict.fromkeys(body.item_ids))
    if not ids:
        raise HTTPException(422, "没有选择条目")
    if not (body.title or body.subject or body.volumes):
        raise HTTPException(422, "至少要指定系列名、条目或卷号")
    if body.skip_metadata and not (body.title or "").strip():
        raise HTTPException(422, "直接整理要先填书名")
    subject = check_choices(body, request)

    def work(organizer: Organizer) -> dict:
        counts = organizer.confirm(ids, title=body.title or None, edition=body.edition or None, subject=subject,
                                   volumes=body.volumes, skip_metadata=body.skip_metadata)
        return auto_execute(request.app, organizer, counts, planned_ids(request.app, ids))

    return submit(request, "confirm", work)


@router.post("/reidentify", response_model=JobRef)
def reidentify(body: Reidentify, request: Request) -> JobRef:
    """Ask the AI again about review items: the given ones, or every one of a library."""
    require_ai(request)
    if body.item_ids:
        ids = list(dict.fromkeys(body.item_ids))
        return submit(request, "reidentify", lambda organizer: auto_execute(
            request.app, organizer, organizer.reidentify(ids), planned_ids(request.app, ids)))
    if body.library_id is None:
        raise HTTPException(422, "要指定条目或库")
    store = ItemStore(request.app.state.db)
    library_id = body.library_id

    def work(organizer):
        ids = [item.id for item in store.list(library_id, ItemStatus.NEEDS_REVIEW)]
        return auto_execute(request.app, organizer, organizer.reidentify(ids), planned_ids(request.app, ids))

    return submit(request, "reidentify", work, library_id=library_id)

