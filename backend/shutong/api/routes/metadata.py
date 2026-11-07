from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, Request

from shutong.api.auth import require_login
from shutong.api.schemas import SubjectOut, subject_out
from shutong.metadata.base import MetadataUnavailable

router = APIRouter(prefix="/api/metadata", tags=["metadata"], dependencies=[Depends(require_login)])


def _source(request: Request):
    return request.app.state.services_factory(request.app.state.db).source


@router.get("/search", response_model=List[SubjectOut])
def search(q: str, request: Request, kind: Literal["manga", "novel"] = "manga") -> List[dict]:
    if not q.strip():
        raise HTTPException(422, "搜索词不能为空")
    try:
        return [subject_out(subject) for subject in _source(request).search(q.strip(), kind)]
    except MetadataUnavailable:
        raise HTTPException(503, "Bangumi 暂时无法访问")


@router.get("/subjects/{subject_id}", response_model=SubjectOut)
def subject(subject_id: int, request: Request) -> dict:
    try:
        return subject_out(_source(request).get(subject_id))
    except MetadataUnavailable:
        raise HTTPException(503, "Bangumi 暂时无法访问")
    except KeyError:
        raise HTTPException(404, "条目不存在")
