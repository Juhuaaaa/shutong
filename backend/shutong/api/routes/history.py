"""Organize history, one record per source folder (the unit a person dropped in)."""
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from fastapi import APIRouter, Depends, Request

from shutong.api.auth import require_login
from shutong.api.schemas import HistoryPage, ItemOut, item_out
from shutong.engine.states import ItemStatus
from shutong.store.records import ItemStore

router = APIRouter(prefix="/api/history", tags=["history"], dependencies=[Depends(require_login)])

_KIND_ORDER = {"volume": 0, "range": 0, "chapter": 1, "special": 2}


@router.get("/groups", response_model=HistoryPage)
def groups(request: Request, library_id: Optional[int] = None, status: Optional[ItemStatus] = None,
           q: Optional[str] = None, missing_metadata: bool = False, ai_picked: bool = False,
           source: Optional[str] = None, limit: int = 30, offset: int = 0) -> dict:
    """``ai_picked`` and ``source`` find organized files worth a second look: the AI chose their entry among
    several, or it came from a given metadata source."""
    found, total = ItemStore(request.app.state.db).group_page(
        library_id, status=status, query=q, missing_metadata=missing_metadata, ai_picked=ai_picked,
        source=source or None, limit=min(max(limit, 1), 200), offset=max(offset, 0))
    return {"groups": [group for group in found if group["group_key"] is not None], "total": total}


@router.get("/groups/{library_id}/{group_key:path}", response_model=List[ItemOut])
def group_items(library_id: int, group_key: str, request: Request, status: Optional[ItemStatus] = None) -> List[dict]:
    items = ItemStore(request.app.state.db).in_group(library_id, group_key)
    if status is not None:
        items = [item for item in items if item.status is status]
    return [item_out(item) for item in sorted(items, key=_volume_order)]


def _volume_order(item):
    """Volumes, then chapters, then specials, each by number; unplanned items last by name."""
    kind, _, value = str(item.plan.get("volume") or "").partition(":")
    try:
        number = Decimal(value.split("-", 1)[0])
    except (InvalidOperation, ValueError):
        return (9, Decimal(0), item.source_path.name)
    return (_KIND_ORDER.get(kind, 3), number, item.source_path.name)
