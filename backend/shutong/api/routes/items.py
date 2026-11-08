from urllib.error import HTTPError
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from shutong.api.auth import require_login
from shutong.api.schemas import CancelResult, ItemDetail, ItemPage, JobRef, SubjectRefIn, ai_call_out, item_out
from shutong.engine import covers
from shutong.engine.metadata_edit import ManualMetadata
from shutong.engine.match import label_of, missing_subject
from shutong.engine.organizer import Organizer, validate_choices
from shutong.metadata.base import MetadataUnavailable
from shutong.servers.notify import notify_published, redone_series
from shutong.engine.states import ItemStatus, ReviewReason
from shutong.store.ai_calls import AiCallStore
from shutong.store.records import ItemStore, LibraryStore

router = APIRouter(prefix="/api/items", tags=["items"], dependencies=[Depends(require_login)])


class Selection(BaseModel):
    item_ids: List[int]


class Reorganize(Selection):
    title: Optional[str] = None
    edition: Optional[str] = None
    subject: Optional[SubjectRefIn] = None
    volumes: Dict[int, str] = {}


class EditMetadata(Selection):
    subject: Optional[SubjectRefIn] = None
    fields: Optional[Dict[str, Any]] = None


class ChooseCover(BaseModel):
    page: str
    left: Optional[float] = None
    right: Optional[float] = None


class JacketOut(BaseModel):
    page: str
    left: float
    right: float


class CoverOptionsOut(BaseModel):
    pages: List[str]
    current: Optional[str]
    added: bool
    jacket: Optional[JacketOut]


class RefreshMetadata(BaseModel):
    item_ids: Optional[List[int]] = None
    library_id: Optional[int] = None


def selected(body: Selection) -> List[int]:
    if not body.item_ids:
        raise HTTPException(422, "没有选择条目")
    return list(dict.fromkeys(body.item_ids))


def _require_subject(source, subject) -> None:
    """Before the job starts: a subject the source does not have is the user's to fix, not a failed job."""
    try:
        source.get(subject.id)
    except MetadataUnavailable:
        raise HTTPException(503, "{0} 暂时无法访问".format(label_of(source)))
    except (KeyError, HTTPError) as error:
        if isinstance(error, HTTPError) and error.code != 404:
            raise HTTPException(502, "{0} 返回错误：{1}".format(label_of(source), error.code))
        raise HTTPException(404, missing_subject(label_of(source), subject.id))


def check_choices(body, request: Request):
    """The chosen subject as a ``SubjectRef``, after checking every choice; 422 for a bad one."""
    sources = request.app.state.services_factory(request.app.state.db).sources.names
    try:
        subject = body.subject.ref() if body.subject is not None else None
        validate_choices(title=body.title or None, edition=body.edition or None, subject=subject,
                         volumes=body.volumes, sources=sources)
    except ValueError as error:
        raise HTTPException(422, str(error))
    return subject


def require_ai(request: Request) -> None:
    """Recognition needs AI: refuse up front instead of failing in the background."""
    if request.app.state.services_factory(request.app.state.db).ai is None:
        raise HTTPException(409, "请先在「设置 → AI」里配置 AI 接口，识别需要用到它")


def submit(request: Request, kind: str, work: Callable[[Organizer], dict], library_id: Optional[int] = None) -> JobRef:
    app = request.app

    def run() -> dict:
        organizer = Organizer(app.state.services_factory(app.state.db))
        organizer.should_stop = app.state.jobs.stop_requested
        return work(organizer)

    return JobRef(job_id=app.state.jobs.submit(kind, run, library_id=library_id).id)


@router.get("", response_model=ItemPage)
def list_items(request: Request, library_id: Optional[int] = None, status: Optional[ItemStatus] = None,
               review_reason: Optional[ReviewReason] = None, q: Optional[str] = None,
               limit: int = 50, offset: int = 0) -> dict:
    items, total = ItemStore(request.app.state.db).page(
        library_id, status=status, review_reason=review_reason, query=q,
        limit=min(max(limit, 1), 500), offset=max(offset, 0))
    return {"items": [item_out(item) for item in items], "total": total}


@router.get("/{item_id}", response_model=ItemDetail)
def read_item(item_id: int, request: Request) -> dict:
    store = ItemStore(request.app.state.db)
    try:
        item = store.get(item_id)
    except KeyError:
        raise HTTPException(404, "条目不存在")
    detail = item_out(item)
    detail["events"] = [{"at": event.at, "kind": event.kind, "detail": event.detail}
                        for event in store.events(item_id)]
    detail["ai_calls"] = [ai_call_out(call) for call in AiCallStore(request.app.state.db).for_item(item_id)]
    return detail


class Publishing:
    """Publish items in as many batches as a job likes, then tell the media servers once."""

    def __init__(self, app, organizer: Organizer) -> None:
        self.app = app
        self.organizer = organizer
        self.counts = {"published": 0, "failed": 0, "review": 0, "skipped": 0}
        self.published: List[int] = []

    def __call__(self, ids: List[int]) -> None:
        if not ids:
            return
        store = ItemStore(self.app.state.db)
        before = {item_id: store.get(item_id).status for item_id in ids}
        for key, value in self.organizer.execute(ids).items():
            self.counts[key] = self.counts.get(key, 0) + value
        self.published += [item_id for item_id in ids if before[item_id] is not ItemStatus.PUBLISHED
                           and store.get(item_id).status is ItemStatus.PUBLISHED]

    def notify(self) -> dict:
        return notify_published(self.app.state.db, self.published, server_factory=self.app.state.server_factory,
                                refresh_series=redone_series(self.app.state.db, self.published))


def execute_and_notify(app, organizer: Organizer, ids: List[int]) -> dict:
    """Publish, then tell the media servers; a notification problem only shows up in ``result["kavita"]``."""
    publishing = Publishing(app, organizer)
    publishing(ids)
    counts = dict(publishing.counts)
    counts["kavita"] = publishing.notify()
    return counts


def planned_ids(app, item_ids: Optional[List[int]] = None, library_id: Optional[int] = None) -> List[int]:
    """Items waiting to be executed: planned, or ready again after a retry."""
    store = ItemStore(app.state.db)
    if item_ids is None:
        return [item.id for status in (ItemStatus.PLANNED, ItemStatus.READY) for item in store.list(library_id, status)]
    return [item_id for item_id in item_ids if store.get(item_id).status in (ItemStatus.PLANNED, ItemStatus.READY)]


def auto_execute(app, organizer: Organizer, counts: dict, candidates: List[int]) -> dict:
    """Publish what this job planned right away and fold the outcome into its counts.

    ``candidates`` are the items the job just planned.
    """
    if not candidates:
        return counts
    done = execute_and_notify(app, organizer, candidates)
    merged = dict(counts)
    merged["executed"] = done["published"]
    merged["planned"] = max(0, merged.get("planned", len(candidates)) - done["published"] - done["failed"] - done["review"])
    if done["failed"]:
        merged["failed"] = merged.get("failed", 0) + done["failed"]
    if done["review"]:
        merged["needs_review"] = merged.get("needs_review", 0) + done["review"]
    merged["kavita"] = done["kavita"]
    return merged


@router.post("/execute", response_model=JobRef)
def execute(body: Selection, request: Request) -> JobRef:
    ids = selected(body)
    return submit(request, "execute", lambda organizer: execute_and_notify(request.app, organizer, ids))


@router.post("/retry", response_model=JobRef)
def retry(body: Selection, request: Request) -> JobRef:
    ids = selected(body)
    return submit(request, "retry", lambda organizer: auto_execute(
        request.app, organizer, organizer.retry(ids), planned_ids(request.app, ids)))


@router.post("/reorganize", response_model=JobRef)
def reorganize(body: Reorganize, request: Request) -> JobRef:
    ids = selected(body)
    subject = check_choices(body, request)

    def work(organizer: Organizer) -> dict:
        counts = organizer.reorganize(ids, title=body.title or None, edition=body.edition or None, subject=subject,
                                      volumes=body.volumes)
        return auto_execute(request.app, organizer, counts, planned_ids(request.app, ids))

    return submit(request, "reorganize", work)


@router.post("/metadata", response_model=JobRef)
def edit_metadata(body: EditMetadata, request: Request) -> JobRef:
    """Rewrite the metadata inside organized files, then have Kavita read them again."""
    ids = selected(body)
    if (body.subject is None) == (body.fields is None):
        raise HTTPException(422, "要选一个条目或手填元数据")
    registry = request.app.state.services_factory(request.app.state.db).sources
    try:
        subject = body.subject.ref() if body.subject is not None else None
        if subject is not None:
            validate_choices(subject=subject, sources=registry.names)
    except ValueError as error:
        raise HTTPException(422, str(error))
    if subject is not None:
        _require_subject(registry.get(subject.source), subject)
    try:
        manual = ManualMetadata.from_json(body.fields) if body.fields is not None else None
    except ValueError as error:
        raise HTTPException(422, str(error))
    app = request.app

    def work(organizer: Organizer) -> dict:
        counts = organizer.edit_metadata(ids, subject=subject, manual=manual)
        series, edited = counts.pop("series"), counts.pop("ids")
        counts["kavita"] = notify_published(app.state.db, edited, server_factory=app.state.server_factory,
                                            refresh_series=series)
        return counts

    return submit(request, "metadata", work)


def _organized_file(request: Request, item_id: int):
    db = request.app.state.db
    try:
        item = ItemStore(db).get(item_id)
    except KeyError:
        raise HTTPException(404, "条目不存在")
    if item.status is not ItemStatus.PUBLISHED or not item.target_path:
        raise HTTPException(409, "只有已整理的文件才有封面")
    library = LibraryStore(db).get(item.library_id)
    if library.kind != "manga":
        raise HTTPException(409, "只有漫画才能换封面")
    path = library.library_dir / item.target_path
    if not path.is_file():
        raise HTTPException(404, "文件不见了")
    return path


@router.get("/{item_id}/cover-options", response_model=CoverOptionsOut)
def cover_options(item_id: int, request: Request) -> dict:
    path = _organized_file(request, item_id)
    try:
        options = covers.cover_options(path)
    except Exception as error:
        raise HTTPException(422, "读不了这个文件：{0}".format(error))
    jacket = options.jacket
    return {"pages": list(options.pages), "current": options.current, "added": options.added,
            "jacket": {"page": jacket.page, "left": jacket.left, "right": jacket.right} if jacket else None}


@router.get("/{item_id}/cover-image")
def cover_image(item_id: int, request: Request, page: Optional[str] = None,
                w: int = Query(240, ge=60, le=1600)) -> Response:
    """The file's cover, or the given page, as a JPEG ``w`` wide; browsers keep it until the address changes."""
    path = _organized_file(request, item_id)
    try:
        data = covers.read_page(path, page) if page is not None else covers.read_cover(path)
        return Response(covers.thumbnail(data, w), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
    except Exception as error:
        raise HTTPException(404, "读不了这张图片：{0}".format(error))


def _told_servers(app, counts: dict) -> dict:
    series, changed = counts.pop("series"), counts.pop("ids")
    counts["kavita"] = notify_published(app.state.db, changed, server_factory=app.state.server_factory,
                                        refresh_series=series)
    return counts


@router.post("/{item_id}/cover", response_model=JobRef)
def choose_cover(item_id: int, body: ChooseCover, request: Request) -> JobRef:
    path = _organized_file(request, item_id)
    try:
        covers.read_page(path, body.page)
    except ValueError as error:
        raise HTTPException(422, str(error))
    if body.left is not None and body.right is not None and not 0 <= body.left < body.right <= 1:
        raise HTTPException(422, "裁剪范围不对")
    app = request.app
    return submit(request, "cover", lambda organizer: _told_servers(
        app, organizer.set_cover(item_id, body.page, body.left, body.right)))


@router.post("/crop-jackets", response_model=JobRef)
def crop_jackets(body: Selection, request: Request) -> JobRef:
    """Crop the front out of every selected volume that starts with a whole dust jacket."""
    ids = selected(body)
    app = request.app

    def work(organizer: Organizer) -> dict:
        organizer.expect(len(ids))
        return _told_servers(app, organizer.crop_jackets(ids))

    return submit(request, "cover", work)


@router.post("/refresh-metadata", response_model=JobRef)
def refresh_metadata(body: RefreshMetadata, request: Request) -> JobRef:
    """Ask Bangumi again about organized files (the given ones, or a whole library's) and write back what changed."""
    if (body.item_ids is None) == (body.library_id is None):
        raise HTTPException(422, "要指定条目或库")
    app = request.app
    store = ItemStore(app.state.db)

    def work(organizer: Organizer) -> dict:
        ids = body.item_ids if body.item_ids is not None else [
            item.id for item in store.list(body.library_id, ItemStatus.PUBLISHED)]
        organizer.expect(len(ids))
        return _told_servers(app, organizer.refresh_metadata(ids))

    return submit(request, "refresh_metadata", work)


@router.post("/cancel", response_model=CancelResult)
def cancel(body: Selection, request: Request) -> dict:
    organizer = Organizer(request.app.state.services_factory(request.app.state.db))
    return organizer.cancel(selected(body))

