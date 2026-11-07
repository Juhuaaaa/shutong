from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from shutong.api.auth import require_login
from shutong.api.schemas import SubjectOut, subject_out
from shutong.metadata.base import MetadataUnavailable
from shutong.metadata.registry import KNOWN_SOURCES

router = APIRouter(prefix="/api/metadata", tags=["metadata"], dependencies=[Depends(require_login)])


class SourceOut(BaseModel):
    name: str
    label: str
    enabled: bool


def _sources(request: Request):
    return request.app.state.services_factory(request.app.state.db).sources


def _source(request: Request, name: Optional[str]):
    sources = _sources(request)
    if not name:
        return sources.primary
    try:
        return sources.get(name)
    except KeyError:
        raise HTTPException(422, "没有这个数据源：{0}".format(name))


@router.get("/sources", response_model=List[SourceOut])
def sources(request: Request) -> List[dict]:
    """Switched-on sources in the order they are asked, then the others."""
    registry = _sources(request)
    enabled = [source.name for source in registry.enabled]
    others = sorted((name for name in registry.names if name not in enabled),
                    key=lambda name: KNOWN_SOURCES.index(name) if name in KNOWN_SOURCES else len(KNOWN_SOURCES))
    return [{"name": name, "label": getattr(registry.get(name), "label", name), "enabled": name in enabled}
            for name in enabled + others]


@router.get("/search", response_model=List[SubjectOut])
def search(q: str, request: Request, kind: Literal["manga", "novel"] = "manga",
           source: Optional[str] = None) -> List[dict]:
    if not q.strip():
        raise HTTPException(422, "搜索词不能为空")
    chosen = _source(request, source)
    try:
        return [subject_out(subject) for subject in chosen.search(q.strip(), kind)]
    except MetadataUnavailable:
        raise HTTPException(503, "{0} 暂时无法访问".format(chosen.label))


@router.get("/subjects/{source}/{subject_id}", response_model=SubjectOut)
def subject(source: str, subject_id: str, request: Request) -> dict:
    chosen = _source(request, source)
    try:
        return subject_out(chosen.get(subject_id))
    except MetadataUnavailable:
        raise HTTPException(503, "{0} 暂时无法访问".format(chosen.label))
    except (KeyError, ValueError):
        raise HTTPException(404, "条目不存在")
