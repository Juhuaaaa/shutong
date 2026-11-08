"""Background jobs: long operations (scan, execute, confirm…) run one at a time off the request thread.

One worker thread keeps building and publishing serial (spec §7.3). Job records live in memory: the
items and runs they change are in the database, so losing the job list on restart loses nothing.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import itertools
import logging
import queue
import time
import threading
from typing import Callable, Dict, List, Optional

from shutong.engine.organizer import LibraryUnavailable
from shutong.labels import COUNTS, HIDDEN_COUNTS

_KEEP = 200  # finished jobs remembered for the job list
_PUSH_EVERY = 1.0  # seconds between progress pushes; a scan reports after every file
_LABELS = {"scan": "扫描", "execute": "执行", "confirm": "复核确认", "reorganize": "重新整理", "retry": "重试",
           "reidentify": "重新识别", "adopt": "采纳 AI 建议"}
log = logging.getLogger("shutong.jobs")


def _label(job: "Job") -> str:
    library = "（库 {0}）".format(job.library_id) if job.library_id is not None else ""
    return "{0} #{1}{2}".format(_LABELS.get(job.kind, job.kind), job.id, library)


def _summary(result: dict) -> str:
    """The numbers of a job result as one line: 已规划 3、复核 2 …; nested dicts by their own numbers."""
    parts = []
    for key, value in result.items():
        if key in HIDDEN_COUNTS:
            continue
        label = COUNTS.get(key, key)
        if isinstance(value, dict):
            inner = _summary(value)
            if inner:
                parts.append("{0}（{1}）".format(label, inner) if label else inner)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            parts.append("{0} {1}".format(label, value))
    return "、".join(parts)


@dataclass
class Job:
    id: int
    kind: str
    library_id: Optional[int] = None
    state: str = "queued"  # queued | running | done | failed | cancelled
    result: dict = field(default_factory=dict)
    error: Optional[str] = None
    progress: Optional[dict] = None  # {"done", "total", "current"} while a long job runs
    cancelling: bool = False  # asked to stop; it does at the next folder or file
    created_at: str = field(default_factory=lambda: _now())
    finished_at: Optional[str] = None

    def public(self) -> dict:
        return asdict(self)


class JobRunner:
    def __init__(self, *, inline: bool = False) -> None:
        self.inline = inline
        self._ids = itertools.count(1)
        self._jobs: Dict[int, Job] = {}
        self._work: "queue.Queue" = queue.Queue()
        self._subscribers: List["queue.Queue"] = []
        self._lock = threading.Lock()
        self._current: Optional[Job] = None
        self._pushed_at = 0.0
        self._thread = None
        if not inline:
            self._thread = threading.Thread(target=self._loop, name="shutong-jobs", daemon=True)
            self._thread.start()

    def submit(self, kind: str, fn: Callable[[], dict], *, library_id: Optional[int] = None) -> Job:
        job = Job(id=next(self._ids), kind=kind, library_id=library_id)
        with self._lock:
            self._jobs[job.id] = job
            self._trim()
        self._publish(job)
        if self.inline:
            self._run(job, fn)
        else:
            self._work.put((job, fn))
        return job

    def get(self, job_id: int) -> Job:
        with self._lock:
            return self._jobs[job_id]

    def recent(self, limit: int = 50) -> List[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.id, reverse=True)[:limit]

    def report(self, progress: dict) -> None:
        """How far the running job is; pushed at most once a second, and always when it is complete."""
        job = self._current
        if job is None:
            return
        job.progress = dict(progress)
        now = time.monotonic()
        complete = progress.get("total") is not None and progress.get("done") == progress.get("total")
        if now - self._pushed_at >= _PUSH_EVERY or complete:
            self._pushed_at = now
            self._publish(job)

    def cancel(self, job_id: int) -> Job:
        """A queued job never runs; a running one stops at its next safe point. Finished ones stay as they are."""
        with self._lock:
            job = self._jobs[job_id]
            if job.state == "queued":
                job.state, job.finished_at = "cancelled", _now()
            elif job.state == "running":
                job.cancelling = True
        self._publish(job)
        return job

    def stop_requested(self) -> bool:
        job = self._current
        return job is not None and job.cancelling

    def subscribe(self) -> "queue.Queue":
        subscriber: "queue.Queue" = queue.Queue()
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: "queue.Queue") -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def stop(self) -> None:
        if self._thread is not None:
            self._work.put(None)
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        while True:
            task = self._work.get()
            if task is None:
                return
            self._run(*task)

    def _run(self, job: Job, fn: Callable[[], dict]) -> None:
        with self._lock:
            if job.state == "cancelled":
                return
            job.state = "running"
        self._current, self._pushed_at = job, 0.0
        self._publish(job)
        started = time.monotonic()
        log.info("开始任务：%s", _label(job))
        try:
            job.result = fn() or {}
            job.state = "cancelled" if job.cancelling else "done"
            log.info("任务完成：%s，用时 %.1f 秒%s", _label(job), time.monotonic() - started,
                     "：" + _summary(job.result) if _summary(job.result) else "")
        except LibraryUnavailable as error:
            job.state, job.error = "failed", "库目录不可用：{0}".format(error)
            log.error("任务失败：%s：%s", _label(job), job.error)
        except Exception as error:  # a failing job must not stop the queue
            job.state, job.error = "failed", "任务失败：{0}: {1}".format(type(error).__name__, error)
            log.exception("任务失败：%s", _label(job))
        job.finished_at = _now()
        self._current = None
        self._publish(job)

    def _publish(self, job: Job) -> None:
        message = {"type": "job", "job": job.public()}
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(message)

    def _trim(self) -> None:
        finished = [job for job in self._jobs.values() if job.state in ("done", "failed", "cancelled")]
        for job in sorted(finished, key=lambda job: job.id)[:-_KEEP]:
            del self._jobs[job.id]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
