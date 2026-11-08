"""Audit log of every AI request: what was sent, what came back, and whether it was adopted."""
from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
from typing import Callable, Dict, List, Optional

from shutong.ai.openai_compat import Usage

from .db import Database


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AiCall:
    id: int
    item_id: Optional[int]
    purpose: str
    model: str
    request_json: str
    response_text: Optional[str]
    error: Optional[str]
    duration_ms: int
    adopted: bool
    created_at: str


class AiCallStore:
    def __init__(self, db: Database, clock: Callable[[], datetime] = _utc_now) -> None:
        self.db = db
        self.clock = clock

    def record(
        self,
        *,
        item_id: Optional[int],
        purpose: str,
        model: str,
        request_json: str,
        response_text: Optional[str],
        error: Optional[str],
        duration_ms: int,
        usage: Optional[Usage] = None,
    ) -> int:
        with self.db.connect() as connection:
            return connection.execute(
                "INSERT INTO ai_calls(item_id, purpose, model, request_json, response_text, error,"
                " duration_ms, created_at, prompt_tokens, completion_tokens, cached_tokens)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item_id, purpose, model, request_json, response_text, error, duration_ms,
                 self.clock().isoformat(), *((usage.prompt, usage.completion, usage.cached) if usage else
                                             (None, None, None))),
            ).lastrowid

    def usage(self, since: Optional[datetime] = None) -> Dict[str, int]:
        """Calls and the tokens they took; ``measured`` counts the calls whose provider said how many."""
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT count(*), count(prompt_tokens), coalesce(sum(prompt_tokens), 0),"
                " coalesce(sum(completion_tokens), 0), coalesce(sum(cached_tokens), 0)"
                " FROM ai_calls WHERE created_at >= ?", (since.isoformat() if since else "",)).fetchone()
        return dict(zip(("calls", "measured", "prompt_tokens", "completion_tokens", "cached_tokens"), row))

    def count_since(self, moment: datetime) -> int:
        with self.db.connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM ai_calls WHERE created_at >= ?", (moment.isoformat(),)
            ).fetchone()[0]

    def for_item(self, item_id: int) -> List[AiCall]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM ai_calls WHERE item_id = ? ORDER BY created_at, id", (item_id,)
            ).fetchall()
        return [_call(row) for row in rows]

    def recent(self, limit: int = 50) -> List[AiCall]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM ai_calls ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_call(row) for row in rows]

    def mark_adopted(self, call_id: int) -> None:
        with self.db.connect() as connection:
            connection.execute("UPDATE ai_calls SET adopted = 1 WHERE id = ?", (call_id,))


def _call(row: sqlite3.Row) -> AiCall:
    return AiCall(
        id=row["id"], item_id=row["item_id"], purpose=row["purpose"], model=row["model"],
        request_json=row["request_json"], response_text=row["response_text"], error=row["error"],
        duration_ms=row["duration_ms"], adopted=bool(row["adopted"]), created_at=row["created_at"],
    )
