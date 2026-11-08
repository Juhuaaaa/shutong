from typing import List, Optional

from pydantic import BaseModel

from fastapi import APIRouter, Depends, Request

from shutong.api.auth import require_login
from shutong.api.schemas import AiCallOut, ai_call_out
from shutong.store.ai_calls import AiCallStore

router = APIRouter(prefix="/api/ai", tags=["ai"], dependencies=[Depends(require_login)])


@router.get("/calls", response_model=List[AiCallOut])
def list_calls(request: Request, item_id: Optional[int] = None, limit: int = 50) -> List[dict]:
    store = AiCallStore(request.app.state.db)
    if item_id is not None:
        return [ai_call_out(call) for call in store.for_item(item_id)]
    return [ai_call_out(call) for call in store.recent(min(max(limit, 1), 500))]


class AiUsageOut(BaseModel):
    calls: int
    measured: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int


@router.get("/usage", response_model=AiUsageOut)
def usage(request: Request) -> dict:
    """Every call so far and the tokens they took."""
    return AiCallStore(request.app.state.db).usage()
