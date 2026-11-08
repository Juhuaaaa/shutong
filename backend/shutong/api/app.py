"""``create_app``: one FastAPI app per data directory, serving the API and (optionally) the web UI."""
from pathlib import Path
from typing import Callable, Optional

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from shutong.api import desktop
from shutong.engine import discard
from shutong.api.auth import Auth
from shutong.api.watcher import SourceWatcher
from shutong.api.jobs import JobRunner
from shutong.api.routes import (ai_calls, auth, dashboard, history, logs, items, jobs, libraries, metadata, review, servers,
                                settings)
from shutong.engine.organizer import Organizer, review_group
from shutong.logs import setup_logging
from shutong.servers.base import MediaServer
from shutong.servers.kavita import server_for
from shutong.services import Services, build_services
from shutong.store.db import Database
from shutong.store.records import ItemStore, LibraryStore, RunStore
from shutong.store.settings import SettingsStore
from shutong.store.servers import ServerRecord


log = logging.getLogger("shutong.app")


def _log_errors(app: FastAPI) -> None:
    """Unexpected errors get their traceback in the log; the page still gets a plain 500."""

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception):
        log.error("接口出错：%s %s", request.method, request.url.path, exc_info=error)
        return JSONResponse({"detail": "服务器内部错误，详情见日志"}, status_code=500)


def _use_trash(desktop: bool) -> None:
    """On the desktop, files Shutong removes go to the system trash."""
    try:
        discard.use_system_trash(desktop)
    except ImportError as error:  # a build without send2trash: delete as on a server, but say so
        logging.getLogger("shutong.app").warning("回收站不可用，删除的文件不会进回收站：%s", error)
        discard.use_system_trash(False)


def create_app(data_dir: Path, *, inline_jobs: bool = False,
               services_factory: Callable[[Database], Services] = build_services,
               server_factory: Callable[[ServerRecord], MediaServer] = server_for,
               web_dist: Optional[Path] = None, log_console: bool = False,
               desktop_token: Optional[str] = None) -> FastAPI:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(data_dir / "shutong.db")
    db.migrate()
    buffer = setup_logging(data_dir, SettingsStore(db).get("log.level"), console=log_console)
    log.info("书童启动：数据目录 %s，数据库版本 %d", data_dir, db.schema_version())
    app = FastAPI(title="书童 Shutong", openapi_url="/api/openapi.json", docs_url="/api/docs", redoc_url=None)
    app.state.db = db
    app.state.data_dir = data_dir
    app.state.logs = buffer
    app.state.desktop = desktop_token is not None
    _use_trash(app.state.desktop)
    app.state.auth = desktop.DesktopAuth(desktop_token) if app.state.desktop else Auth(db)
    if app.state.desktop:
        app.add_middleware(desktop.DesktopGuard)
    app.state.services_factory = services_factory
    app.state.server_factory = server_factory
    app.state.jobs = JobRunner(inline=inline_jobs)
    _startup(db, services_factory)
    _log_errors(app)
    for module in (auth, jobs, dashboard, logs, libraries, items, history, review, metadata, settings, ai_calls, servers,
                   desktop):
        app.include_router(module.router)
    if web_dist is not None and Path(web_dist).is_dir():
        _serve_web(app, Path(web_dist))
    app.state.watcher = SourceWatcher(app)
    if not inline_jobs:  # tests drive the watcher by hand
        app.state.watcher.start()
    return app


def _startup(db: Database, services_factory) -> None:
    """Settle interrupted publications and fill missing group keys before serving."""
    Organizer(services_factory(db)).recover()
    closed = RunStore(db).close_interrupted()
    if closed:
        log.info("有 %d 次扫描被重启打断，已记为中断；没整理完的文件下次扫描会继续", closed)
    _backfill_group_keys(db)


def _backfill_group_keys(db: Database) -> None:
    libraries = {library.id: library for library in LibraryStore(db).all()}

    def resolve(library_id: int, path: Path) -> str:
        try:
            return review_group(libraries[library_id], path)
        except ValueError:  # the library's source dir was changed after this item was scanned
            return path.parent.name or path.name

    filled = ItemStore(db).backfill_group_keys(resolve)
    if filled:
        log.info("给 %d 个旧条目补上了来源目录分组", filled)


# The page is checked with the server every time: after an upgrade it must name the new bundles.
_NO_CACHE = {"Cache-Control": "no-cache"}


def _serve_web(app: FastAPI, root: Path) -> None:
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "接口不存在")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root.resolve() in candidate.parents:
            if path.startswith("assets/"):  # names carry a content hash: a new build is new names
                return FileResponse(candidate, headers={"Cache-Control": "public, max-age=31536000, immutable"})
            return FileResponse(candidate, headers=_NO_CACHE if candidate == index.resolve() else None)
        if path.startswith("assets/"):
            # A bundle an older page asks for: a 404 lets the page reload itself, the page served as a script would not.
            raise HTTPException(404, "文件不存在")
        return FileResponse(index, headers=_NO_CACHE)
