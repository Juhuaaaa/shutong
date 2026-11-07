"""Every AI call goes through here and leaves an audit row, win or lose."""
from datetime import datetime, timezone
import json
import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple

from shutong.store.ai_calls import AiCallStore

from .openai_compat import AiError

log = logging.getLogger("shutong.ai")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuditedAi:
    def __init__(self, provider, calls: AiCallStore, clock: Callable[[], datetime] = _utc_now) -> None:
        self.provider = provider
        self.calls = calls
        self.clock = clock

    def complete_json(self, purpose: str, system: str, payload: Dict[str, Any], *,
                      item_id: Optional[int] = None) -> Tuple[Dict[str, Any], int]:
        request_json = json.dumps({"system": system, "payload": payload}, ensure_ascii=False)
        started = time.monotonic()
        try:
            result, raw = self.provider.complete_json(system, payload)
        except AiError as error:
            self._record(item_id, purpose, request_json, error.raw, str(error), started)
            log.warning("AI 调用失败（%s，%s）：%s", purpose, self.provider.model, error)
            raise
        except Exception as error:  # any provider bug still gets an audit row and an AiError
            self._record(item_id, purpose, request_json, None, str(error), started)
            log.warning("AI 调用出错（%s，%s）：%s", purpose, self.provider.model, error)
            raise AiError("AI provider failed: {0}".format(error)) from error
        call_id = self._record(item_id, purpose, request_json, raw, None, started)
        log.info("AI 调用（%s，%s）用时 %.1f 秒", purpose, self.provider.model, time.monotonic() - started)
        return result, call_id

    def _record(self, item_id, purpose, request_json, response_text, error, started) -> int:
        return self.calls.record(
            item_id=item_id, purpose=purpose, model=self.provider.model, request_json=request_json,
            response_text=response_text, error=error,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
