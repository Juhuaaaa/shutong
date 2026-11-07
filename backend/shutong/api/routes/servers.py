import sqlite3
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from shutong.api.auth import require_login
from shutong.api.schemas import ServerOut, ServerTestOut
from shutong.servers.base import ServerError
from shutong.store.servers import ServerRecord, ServerStore

router = APIRouter(prefix="/api/servers", tags=["servers"], dependencies=[Depends(require_login)])
_MASK = "已设置"


def _check_url(value: Optional[str]) -> Optional[str]:
    if value is not None and not value.startswith(("http://", "https://")):
        raise ValueError("地址要以 http:// 或 https:// 开头")
    return value


class ServerIn(BaseModel):
    kind: Literal["kavita", "komga"] = "kavita"
    name: str
    base_url: str
    username: str = ""
    password: str = ""

    _url = field_validator("base_url")(_check_url)


class ServerPatch(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    enabled: Optional[bool] = None

    _url = field_validator("base_url")(_check_url)


def server_out(record: ServerRecord) -> dict:
    return {"id": record.id, "kind": record.kind, "name": record.name, "base_url": record.base_url,
            "username": record.username, "password": _MASK if record.password else "", "enabled": record.enabled}


def _get(store: ServerStore, server_id: int) -> ServerRecord:
    try:
        return store.get(server_id)
    except KeyError:
        raise HTTPException(404, "媒体服务器不存在")


@router.get("", response_model=List[ServerOut])
def list_servers(request: Request) -> List[dict]:
    return [server_out(record) for record in ServerStore(request.app.state.db).all()]


@router.post("", response_model=ServerOut)
def create_server(body: ServerIn, request: Request) -> dict:
    try:
        record = ServerStore(request.app.state.db).create(body.kind, body.name.strip(), body.base_url,
                                                          body.username, body.password)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "媒体服务器名已存在")
    return server_out(record)


@router.patch("/{server_id}", response_model=ServerOut)
def update_server(server_id: int, body: ServerPatch, request: Request) -> dict:
    store = ServerStore(request.app.state.db)
    _get(store, server_id)
    password = None if body.password == _MASK else body.password
    try:
        record = store.update(server_id, name=body.name, base_url=body.base_url, username=body.username,
                              password=password, enabled=body.enabled)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "媒体服务器名已存在")
    return server_out(record)


@router.delete("/{server_id}", response_model=dict)
def delete_server(server_id: int, request: Request) -> dict:
    store = ServerStore(request.app.state.db)
    _get(store, server_id)
    store.delete(server_id)
    return {"ok": True}


@router.post("/{server_id}/test", response_model=ServerTestOut)
def test_server(server_id: int, request: Request) -> dict:
    record = _get(ServerStore(request.app.state.db), server_id)
    server = request.app.state.server_factory(record)
    try:
        server.test()
        libraries = [{"id": entry.id, "name": entry.name} for entry in server.libraries()]
    except ServerError as error:
        return {"ok": False, "error": str(error), "libraries": []}
    return {"ok": True, "error": None, "libraries": libraries}
