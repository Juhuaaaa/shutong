"""The program log for the web page: newest records from memory, the whole file as a download."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from shutong.api.auth import require_login
from shutong.logs import log_file

router = APIRouter(prefix="/api/logs", tags=["logs"], dependencies=[Depends(require_login)])


class LogEntry(BaseModel):
    seq: int
    at: str
    level: str
    logger: str
    message: str


class LogPage(BaseModel):
    entries: List[LogEntry]
    last_seq: int


@router.get("", response_model=LogPage)
def read_logs(request: Request, after: int = 0, level: Optional[str] = None, q: Optional[str] = None,
              limit: int = 500) -> dict:
    entries, last = request.app.state.logs.since(max(after, 0), level=level, query=q, limit=min(max(limit, 1), 2000))
    return {"entries": entries, "last_seq": last}


@router.get("/download")
def download(request: Request) -> FileResponse:
    path = log_file(request.app.state.data_dir)
    if not path.is_file():
        raise HTTPException(404, "还没有日志文件")
    return FileResponse(path, media_type="text/plain; charset=utf-8", filename="shutong.log")
