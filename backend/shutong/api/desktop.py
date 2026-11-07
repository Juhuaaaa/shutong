"""Desktop mode: no password, a random token per start, and only the app's own window gets in.

The cookie alone is not enough: other pages on 127.0.0.1 count as the same site, so SameSite lets them
send it. Requests must name this machine in Host (that also stops DNS rebinding) and, when they carry an
Origin, come from the very address they are sent to.
"""
import hmac
import json
import os
from pathlib import Path
import re
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from shutong.api.auth import require_login
from shutong.engine.dropped import resolve_drops
from shutong.engine.organizer import adapter_for
from shutong.engine.fingerprint import fingerprint
from shutong.engine.states import ItemStatus
from shutong.store.db import Database
from shutong.store.records import Item, ItemStore, LibraryStore

_LOOPBACK_HOST = re.compile(r"^127\.0\.0\.1:\d+$")
_JUNK_FILES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})
_PASSWORD_PATHS = frozenset({"/api/auth/setup", "/api/auth/login", "/api/auth/logout", "/api/auth/password"})


class DesktopAuth:
    """Same questions as :class:`~shutong.api.auth.Auth`, answered by the token Electron handed us."""

    configured = True

    def __init__(self, token: str) -> None:
        self._token = token

    def valid(self, token: Optional[str]) -> bool:
        return bool(token) and hmac.compare_digest(token.encode("utf-8"), self._token.encode("utf-8"))


class DesktopGuard:
    """Plain ASGI, so that WebSockets are covered too."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if not _allowed(scope):
            if scope["type"] == "http":
                await _respond(send, 403, "不允许的来源")
            else:
                await send({"type": "websocket.close", "code": 4403})
            return
        if scope["type"] == "http" and scope["path"] in _PASSWORD_PATHS:
            await _respond(send, 404, "接口不存在")
            return
        await self.app(scope, receive, send)


def _allowed(scope) -> bool:
    headers = {name: value.decode("latin-1") for name, value in scope["headers"]}
    host = headers.get(b"host", "")
    if not _LOOPBACK_HOST.match(host):
        return False
    origin = headers.get(b"origin")
    return origin is None or origin == "http://" + host


async def _respond(send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def require_desktop(request: Request) -> None:
    if not request.app.state.desktop:
        raise HTTPException(404, "接口不存在")


# Always part of the schema, so the web UI gets its types; ``require_desktop`` keeps them out of the web version.
router = APIRouter(tags=["desktop"], dependencies=[Depends(require_login), Depends(require_desktop)])


class ScanPathsIn(BaseModel):
    paths: List[str]


class SkippedPath(BaseModel):
    path: str
    reason: str


class ScanPathsOut(BaseModel):
    job_id: Optional[int]
    skipped: List[SkippedPath]
    rejected: List[str]


@router.post("/api/libraries/{library_id}/scan-paths", response_model=ScanPathsOut)
def scan_paths(library_id: int, body: ScanPathsIn, request: Request) -> ScanPathsOut:
    from shutong.api.routes.items import require_ai
    from shutong.api.routes.libraries import get_library, submit_scan

    library = get_library(request, library_id)
    paths = [Path(path) for path in body.paths]
    if not paths or not all(path.is_absolute() for path in paths):
        raise HTTPException(422, "需要文件的完整路径")
    require_ai(request)
    found = resolve_drops(adapter_for(library), paths, library.library_dir)
    job = submit_scan(request.app, library, "drop", entries=found.entries) if found.entries else None
    return ScanPathsOut(job_id=job.id if job is not None else None,
                        skipped=[SkippedPath(path=str(item.path), reason=item.reason) for item in found.skipped],
                        rejected=[str(path) for path in found.rejected])


class OriginalOut(BaseModel):
    id: int
    library_id: int
    path: str
    name: str


class OriginalsOut(BaseModel):
    items: List[OriginalOut]


class ItemIds(BaseModel):
    ids: List[int]


class Ok(BaseModel):
    ok: bool = True


class TrashedOut(BaseModel):
    empty_dirs: List[str]


def _still_the_original(item: Item) -> bool:
    """The very file that went into the library: anything changed since then is not ours to offer away."""
    try:
        return os.path.lexists(item.source_path) and fingerprint(item.source_path) == item.fingerprint
    except OSError:
        return False


def _in_library(item: Item, libraries: Dict[int, Path]) -> bool:
    """The library copy is really there: a deleted file or an unplugged disk must not make the original look spare."""
    if item.target_path is None or item.library_id not in libraries:
        return False
    return (libraries[item.library_id] / item.target_path).exists()


def _offerable(db: Database) -> List[Item]:
    libraries = {library.id: Path(library.library_dir) for library in LibraryStore(db).all()}
    return [item for item in ItemStore(db).with_source_root()
            if item.status is ItemStatus.PUBLISHED and not item.originals_kept
            and _in_library(item, libraries) and _still_the_original(item)]


@router.get("/api/desktop/originals", response_model=OriginalsOut)
def originals(request: Request) -> OriginalsOut:
    """Dropped files that are safely in the library and can go, if the user says so."""
    return OriginalsOut(items=[OriginalOut(id=item.id, library_id=item.library_id, path=str(item.source_path),
                                           name=item.source_path.name)
                               for item in _offerable(request.app.state.db)])


@router.post("/api/desktop/originals/keep", response_model=Ok)
def keep_originals(body: ItemIds, request: Request) -> Ok:
    store = ItemStore(request.app.state.db)
    for item in store.with_source_root():
        if item.id in body.ids:
            store.update(item.id, event="originals_kept", originals_kept=1)
    return Ok()


@router.post("/api/desktop/originals/trashed", response_model=TrashedOut)
def originals_trashed(body: ItemIds, request: Request) -> TrashedOut:
    """Electron moved these to the trash. Answers which folders only junk is left in, for it to trash as well."""
    store = ItemStore(request.app.state.db)
    gone = [item for item in store.with_source_root()
            if item.id in body.ids and not os.path.lexists(item.source_path)]
    for item in gone:
        store.add_event(item.id, "source_disposed", {"outcome": "trashed", "destination": None})
    return TrashedOut(empty_dirs=[str(path) for path in _left_empty(gone)])


def _left_empty(items: List[Item]) -> List[Path]:
    """The outermost folders under each item's root holding nothing but junk. Never the root: it may be
    any folder of the user's, the Downloads folder a single file was dropped from."""
    candidates: Set[Path] = set()
    for item in items:
        for parent in item.source_path.parents:
            if parent == item.source_root or item.source_root not in parent.parents:
                break
            candidates.add(parent)
    empty: Set[Path] = set()
    for folder in sorted(candidates, key=lambda path: len(path.parts), reverse=True):
        try:
            children = list(folder.iterdir())
        except OSError:
            continue
        if all(child in empty or child.name.casefold() in _JUNK_FILES for child in children):
            empty.add(folder)
    return sorted(folder for folder in empty if folder.parent not in empty)
