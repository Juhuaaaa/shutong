import asyncio
import queue
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from pydantic import BaseModel

from shutong.api.auth import require_login, websocket_logged_in

router = APIRouter(tags=["jobs"])


class JobOut(BaseModel):
    id: int
    kind: str
    library_id: Optional[int]
    state: str
    result: dict
    error: Optional[str]
    progress: Optional[dict] = None
    cancelling: bool = False
    created_at: str
    finished_at: Optional[str]


class JobRef(BaseModel):
    job_id: int


@router.get("/api/jobs", response_model=List[JobOut], dependencies=[Depends(require_login)])
def list_jobs(request: Request, limit: int = 50) -> List[dict]:
    return [job.public() for job in request.app.state.jobs.recent(min(max(limit, 1), 200))]


@router.get("/api/jobs/{job_id}", response_model=JobOut, dependencies=[Depends(require_login)])
def get_job(job_id: int, request: Request) -> dict:
    try:
        return request.app.state.jobs.get(job_id).public()
    except KeyError:
        raise HTTPException(404, "任务不存在")


@router.post("/api/jobs/{job_id}/cancel", response_model=JobOut, dependencies=[Depends(require_login)])
def cancel_job(job_id: int, request: Request) -> dict:
    try:
        return request.app.state.jobs.cancel(job_id).public()
    except KeyError:
        raise HTTPException(404, "任务不存在")


@router.websocket("/api/ws")
async def updates(websocket: WebSocket) -> None:
    """Pushes ``{"type": "job", "job": {...}}`` on every job state change."""
    await websocket.accept()
    if not websocket_logged_in(websocket):
        # Accept first: browsers only see a close code (4401 = not logged in) on an accepted socket.
        await websocket.close(code=4401)
        return
    jobs = websocket.app.state.jobs
    subscriber = jobs.subscribe()

    async def forward() -> None:
        while True:
            message = await asyncio.to_thread(_next, subscriber)
            if message is not None:
                await websocket.send_json(message)

    async def until_closed() -> None:
        # The client never sends anything; receiving is how a closed tab is noticed.
        while True:
            if (await websocket.receive())["type"] == "websocket.disconnect":
                return

    tasks = [asyncio.ensure_future(forward()), asyncio.ensure_future(until_closed())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()  # the polling thread finishes its current 0.5 s wait on its own
        jobs.unsubscribe(subscriber)


def _next(subscriber: "queue.Queue", timeout: float = 0.5):
    try:
        return subscriber.get(timeout=timeout)
    except queue.Empty:
        return None
