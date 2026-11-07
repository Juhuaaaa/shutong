import time
from typing import Any, Dict
from urllib.request import Request as HttpRequest

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from shutong.api.auth import require_login
from shutong.api.schemas import AiTestResult, ProxyTestIn, ProxyTestResult
from shutong.metadata.bangumi import USER_AGENT
from shutong.metadata.registry import KNOWN_SOURCES
from shutong.logs import LEVELS, set_level
from shutong.net import make_opener, parse_proxy
from shutong.store.settings import DEFAULTS, SECRET_KEYS, SettingsStore

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_login)])

# Secrets and plain text default to None / "": any string (or null) is accepted for them.
_STRING_KEYS = frozenset(key for key, value in DEFAULTS.items() if value is None or isinstance(value, str))


# Values outside these bounds would do damage.
_RANGES = {"ai.threshold": (0.0, 1.0)}


def public(store: SettingsStore) -> Dict[str, Any]:
    return {key: value for key, value in store.public().items() if not key.startswith("auth.")}


def _check(key: str, value: Any) -> None:
    if key.startswith("auth.") or key not in DEFAULTS:
        raise HTTPException(422, "未知设置：{0}".format(key))
    default = DEFAULTS[key]
    if key in _STRING_KEYS:
        ok = value is None or isinstance(value, str)
    elif isinstance(default, list):
        ok = isinstance(value, list)
    elif isinstance(default, bool):
        ok = isinstance(value, bool)
    elif isinstance(default, int):
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif isinstance(default, float):
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    else:
        ok = False
    if not ok:
        raise HTTPException(422, "设置 {0} 的值类型不对".format(key))
    if key in _RANGES:
        low, high = _RANGES[key]
        if not low <= value <= high:
            raise HTTPException(422, "设置 {0} 必须在 {1} 到 {2} 之间".format(key, low, high))
    if key == "log.level" and value not in LEVELS:
        raise HTTPException(422, "日志级别只能是 {0}".format("、".join(LEVELS)))
    if key == "metadata.sources":
        if not value or len(set(map(repr, value))) != len(value) \
                or not all(isinstance(name, str) and name in KNOWN_SOURCES for name in value):
            raise HTTPException(422, "数据源至少开一个，不能重复，只能是：{0}".format("、".join(KNOWN_SOURCES)))
    if key == "network.proxy":
        try:
            parse_proxy(value or "")
        except ValueError as error:
            raise HTTPException(422, str(error))


@router.get("", response_model=Dict[str, Any])
def read_settings(request: Request) -> Dict[str, Any]:
    return public(SettingsStore(request.app.state.db))


@router.patch("", response_model=Dict[str, Any])
def update_settings(request: Request, changes: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    for key, value in changes.items():
        _check(key, value)
    store = SettingsStore(request.app.state.db)
    for key, value in changes.items():
        if key in SECRET_KEYS and value == "已设置":
            continue  # the masked value echoed back from the form: keep the stored secret
        store.set(key, float(value) if isinstance(DEFAULTS[key], float) else value)
    if "log.level" in changes:
        set_level(changes["log.level"])
    return public(store)


@router.post("/ai-test", response_model=AiTestResult)
def ai_test(request: Request) -> AiTestResult:
    services = request.app.state.services_factory(request.app.state.db)
    if services.ai is None:
        return AiTestResult(ok=False, error="没有配置 AI，或 AI 未启用")
    try:
        services.ai.complete_json("connection_test", 'Return only the JSON {"ok": true}.', {})
    except Exception as error:
        return AiTestResult(ok=False, error="{0}: {1}".format(type(error).__name__, error))
    return AiTestResult(ok=True, error=None)


@router.post("/proxy-test", response_model=ProxyTestResult)
def proxy_test(request: Request, body: ProxyTestIn = Body(default_factory=ProxyTestIn)) -> ProxyTestResult:
    """One Bangumi request through the given proxy (or the saved one when omitted)."""
    store = SettingsStore(request.app.state.db)
    text = body.proxy if body.proxy is not None else store.get("network.proxy") or ""
    started = time.monotonic()
    try:
        opener = make_opener(parse_proxy(text))
        url = store.get("bangumi.base_url").rstrip("/") + "/v0/subjects/1"
        with opener(HttpRequest(url, headers={"User-Agent": USER_AGENT}), timeout=15) as response:
            response.read()
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else "{0}: {1}".format(type(error).__name__, error)
        return ProxyTestResult(ok=False, error=message, elapsed_ms=int((time.monotonic() - started) * 1000))
    return ProxyTestResult(ok=True, error=None, elapsed_ms=int((time.monotonic() - started) * 1000))
