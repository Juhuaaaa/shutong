import json
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from shutong.api.auth import require_login
from shutong.api.routes.items import Publishing, planned_ids, require_ai
from shutong.api.schemas import JobRef, LibraryOut, RunOut, Summary, TemplateExample, TemplatePreview, UploadResult
from shutong.api.upload import save_upload
from shutong.engine.organizer import Organizer
from shutong.engine.template import TemplateError, render, validate_template
from shutong.store.records import KEEP, Library, LibraryStore, RunStore
from shutong.store.servers import ServerStore

router = APIRouter(prefix="/api/libraries", tags=["libraries"], dependencies=[Depends(require_login)])

Kind = Literal["manga", "novel"]
Policy = Literal["keep", "archive", "delete"]
Overwrite = Literal["never", "always", "larger", "newer"]


class LibraryIn(BaseModel):
    name: str
    kind: Kind
    source_dir: str = ""  # empty: files only come in through uploads
    library_dir: str
    naming_template: str = ""
    source_policy: Policy = "keep"
    archive_dir: Optional[str] = None
    pdf_to_cbz: bool = True
    include_edition: bool = True
    overwrite_policy: Overwrite = "never"
    rename_files: bool = True
    server_id: Optional[int] = None
    server_library_id: Optional[int] = None
    watch: bool = False


class LibraryPatch(BaseModel):
    name: Optional[str] = None
    source_dir: Optional[str] = None
    library_dir: Optional[str] = None
    naming_template: Optional[str] = None
    source_policy: Optional[Policy] = None
    archive_dir: Optional[str] = None
    pdf_to_cbz: Optional[bool] = None
    include_edition: Optional[bool] = None
    overwrite_policy: Optional[Overwrite] = None
    rename_files: Optional[bool] = None
    server_id: Optional[int] = None
    server_library_id: Optional[int] = None
    watch: Optional[bool] = None


class TemplateIn(BaseModel):
    template: str


def library_out(library: Library) -> LibraryOut:
    return LibraryOut(
        id=library.id, name=library.name, kind=library.kind,
        source_dir="" if library.source_managed else str(library.source_dir), watch=library.watch,
        library_dir=str(library.library_dir), naming_template=library.naming_template,
        source_policy=library.source_policy,
        archive_dir=str(library.archive_dir) if library.archive_dir is not None else None,
        pdf_to_cbz=library.pdf_to_cbz, include_edition=library.include_edition,
        overwrite_policy=library.overwrite_policy, rename_files=library.rename_files, server_id=library.server_id, server_library_id=library.server_library_id,
        available=(library.source_managed or Path(library.source_dir).is_dir()) and Path(library.library_dir).is_dir(),
    )


def get_library(request: Request, library_id: int) -> Library:
    try:
        return LibraryStore(request.app.state.db).get(library_id)
    except KeyError:
        raise HTTPException(404, "库不存在")


def _check_template(template: str) -> None:
    if template:
        try:
            validate_template(template)
        except TemplateError as error:
            raise HTTPException(422, str(error))


def _check_policy(policy: str, archive_dir: Optional[str]) -> None:
    if policy == "archive" and not archive_dir:
        raise HTTPException(422, "「移到原档目录」需要填写原档目录")


def _check_source(source_dir: str, policy: str, watch: bool, desktop: bool = False) -> None:
    if source_dir.strip():
        return
    if policy == "keep" and not desktop:  # the desktop app's files stay in the user's folders, not in uploads
        raise HTTPException(422, "来源目录留空时，整理后只能删除原文件或移到原档目录")
    if watch:
        raise HTTPException(422, "来源目录留空时不能开目录监控")


def _check_server(request: Request, server_id: Optional[int]) -> None:
    if server_id is not None:
        try:
            ServerStore(request.app.state.db).get(server_id)
        except KeyError:
            raise HTTPException(422, "媒体服务器不存在")


def _check_name(store: LibraryStore, name: str, library_id: Optional[int] = None) -> None:
    if not name.strip():
        raise HTTPException(422, "库名不能为空")
    try:
        existing = store.by_name(name)
    except KeyError:
        return
    if existing.id != library_id:
        raise HTTPException(409, "库名已存在")


@router.get("", response_model=List[LibraryOut])
def list_libraries(request: Request) -> List[LibraryOut]:
    return [library_out(library) for library in LibraryStore(request.app.state.db).all()]


def _create_library_dir(library_dir: str) -> None:
    path = Path(library_dir.strip())
    if not path.is_absolute():
        raise HTTPException(422, f"库目录要写完整路径：{library_dir}")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise HTTPException(422, f"无法创建库目录 {library_dir}：{error.strerror or error}") from None


@router.post("", response_model=LibraryOut)
def create_library(body: LibraryIn, request: Request) -> LibraryOut:
    store = LibraryStore(request.app.state.db)
    _check_name(store, body.name)
    _check_template(body.naming_template)
    _check_policy(body.source_policy, body.archive_dir)
    _check_source(body.source_dir, body.source_policy, body.watch, request.app.state.desktop)
    _check_server(request, body.server_id)
    if request.app.state.desktop:
        _create_library_dir(body.library_dir)
    source = Path(body.source_dir.strip()) if body.source_dir.strip() else ""
    library = store.create(body.name.strip(), body.kind, source, Path(body.library_dir),
                           source_policy=body.source_policy,
                           archive_dir=Path(body.archive_dir) if body.archive_dir else None,
                           naming_template=body.naming_template, pdf_to_cbz=body.pdf_to_cbz,
                           include_edition=body.include_edition, watch=body.watch,
                           overwrite_policy=body.overwrite_policy, rename_files=body.rename_files)
    if body.server_id is not None:
        library = store.update(library.id, server_id=body.server_id, server_library_id=body.server_library_id)
    return library_out(library)


@router.get("/{library_id}", response_model=LibraryOut)
def read_library(library_id: int, request: Request) -> LibraryOut:
    return library_out(get_library(request, library_id))


@router.patch("/{library_id}", response_model=LibraryOut)
def update_library(library_id: int, body: LibraryPatch, request: Request) -> LibraryOut:
    library = get_library(request, library_id)
    store = LibraryStore(request.app.state.db)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        _check_name(store, changes["name"], library.id)
    if changes.get("naming_template"):
        _check_template(changes["naming_template"])
    policy = changes.get("source_policy") or library.source_policy
    archive = changes["archive_dir"] if "archive_dir" in changes else (
        str(library.archive_dir) if library.archive_dir else None)
    _check_policy(policy, archive)
    source = changes["source_dir"] if "source_dir" in changes and changes["source_dir"] is not None else (
        "" if library.source_managed else str(library.source_dir))
    watch = changes["watch"] if changes.get("watch") is not None else library.watch
    if not source.strip() and "watch" not in changes:
        watch = False  # dropping the source dir turns watching off
    _check_source(source, policy, watch, request.app.state.desktop)
    if request.app.state.desktop and changes.get("library_dir"):
        _create_library_dir(changes["library_dir"])
    if "server_id" in changes:
        _check_server(request, changes["server_id"])
    updated = store.update(
        library.id, name=changes.get("name"), naming_template=changes.get("naming_template"),
        source_policy=changes.get("source_policy"), pdf_to_cbz=changes.get("pdf_to_cbz"),
        include_edition=changes.get("include_edition"),
        overwrite_policy=changes.get("overwrite_policy"), rename_files=changes.get("rename_files"),
        source_dir=(Path(source.strip()) if source.strip() else "") if "source_dir" in changes else None,
        watch=watch if watch != library.watch else None,
        library_dir=Path(changes["library_dir"]) if changes.get("library_dir") else None,
        archive_dir=(Path(archive) if archive else None) if "archive_dir" in changes else KEEP,
        server_id=changes["server_id"] if "server_id" in changes else KEEP,
        server_library_id=changes["server_library_id"] if "server_library_id" in changes else (
            None if changes.get("server_id", KEEP) is None else KEEP),
    )
    return library_out(updated)


def submit_scan(app, library: Library, trigger: str = "manual", entries=None):
    """Queue a scan of the library, or of ``entries`` when given; each folder is published as soon as it is planned."""

    def run() -> dict:
        organizer = Organizer(app.state.services_factory(app.state.db))
        organizer.on_progress = app.state.jobs.report
        organizer.should_stop = app.state.jobs.stop_requested
        publishing = Publishing(app, organizer)
        # Each folder goes into the library as soon as it is planned, before the next one is looked at.
        if entries is None:
            run_id = organizer.scan(library.id, trigger, on_planned=publishing)
        else:
            run_id = organizer.scan_paths(library.id, entries, on_planned=publishing)
        # Then what an earlier, interrupted run left planned.
        leftovers = planned_ids(app, library_id=library.id)
        organizer.expect(len(leftovers))
        publishing(leftovers)
        counts = dict(RunStore(app.state.db).counts(run_id))
        counts["executed"] = publishing.counts["published"]
        counts.setdefault("planned", 0)
        counts["kavita"] = publishing.notify()
        return {"run_id": run_id, "counts": counts}

    return app.state.jobs.submit("scan", run, library_id=library.id)


@router.post("/{library_id}/scan", response_model=JobRef)
def scan_library(library_id: int, request: Request) -> JobRef:
    library = get_library(request, library_id)
    require_ai(request)
    return JobRef(job_id=submit_scan(request.app, library).id)


@router.get("/{library_id}/runs", response_model=List[RunOut])
def list_runs(library_id: int, request: Request, limit: int = 20) -> List[RunOut]:
    get_library(request, library_id)
    with request.app.state.db.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM runs WHERE library_id = ? ORDER BY id DESC LIMIT ?",
            (library_id, min(max(limit, 1), 200))).fetchall()
    return [RunOut(id=row["id"], trigger=row["trigger"], started_at=row["started_at"],
                   finished_at=row["finished_at"], counts=json.loads(row["counts"])) for row in rows]


@router.get("/{library_id}/summary", response_model=Summary)
def summary(library_id: int, request: Request) -> Summary:
    get_library(request, library_id)
    with request.app.state.db.connect() as connection:
        rows = connection.execute("SELECT status, count(*) AS n FROM items WHERE library_id = ? GROUP BY status",
                                  (library_id,)).fetchall()
    return Summary(counts={row["status"]: row["n"] for row in rows})


@router.get("/{library_id}/series", response_model=List[str])
def series_directories(library_id: int, request: Request) -> List[str]:
    """Series folders already in the media library (first level, hidden ones left out)."""
    library = get_library(request, library_id)
    root = Path(library.library_dir)
    if not root.is_dir():
        raise HTTPException(409, "库目录不可用")
    return sorted(entry.name for entry in root.iterdir() if entry.is_dir() and not entry.name.startswith("."))


@router.post("/{library_id}/template-preview", response_model=TemplatePreview)
def template_preview(library_id: int, body: TemplateIn, request: Request) -> TemplatePreview:
    get_library(request, library_id)
    _check_template(body.template or "")
    if not body.template:
        raise HTTPException(422, "命名模板不能为空")
    with request.app.state.db.connect() as connection:
        rows = connection.execute(
            "SELECT source_path, plan FROM items WHERE library_id = ? AND status IN ('planned', 'published')"
            " ORDER BY id DESC LIMIT 50", (library_id,)).fetchall()
    examples = []
    for row in rows:
        fields = json.loads(row["plan"]).get("fields")
        if not fields:
            continue
        try:
            target = render(body.template, fields).as_posix()
        except TemplateError as error:
            raise HTTPException(422, str(error))
        examples.append(TemplateExample(source=Path(row["source_path"]).name, target=target))
        if len(examples) == 5:
            break
    return TemplatePreview(examples=examples)


@router.post("/{library_id}/upload", response_model=UploadResult)
def upload(library_id: int, request: Request, files: List[UploadFile] = File(...)) -> dict:
    """Save files into the source directory by their relative path; scanning is a separate step."""
    library = get_library(request, library_id)
    if not Path(library.source_dir).is_dir():
        raise HTTPException(409, "库目录不可用")
    saved, skipped = [], []
    for upload_file in files:
        try:
            path = save_upload(library, upload_file.filename or "", upload_file.file)
        except ValueError as error:
            raise HTTPException(422, "{0}（已保存 {1} 个文件）".format(error, len(saved)))
        except OSError as error:
            raise HTTPException(422, "保存 {0} 失败：{1}（已保存 {2} 个文件）".format(
                upload_file.filename, error.strerror or error, len(saved)))
        if path is None:
            skipped.append(upload_file.filename)
            continue
        saved.append({"name": upload_file.filename, "path": path.as_posix()})
    return {"saved": saved, "skipped": skipped}
