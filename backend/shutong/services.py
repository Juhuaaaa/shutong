"""Wire the metadata source, AI and engine options from stored settings."""
from dataclasses import dataclass
import time
from typing import Optional
from urllib.request import urlopen

from shutong.ai.audit import AuditedAi
from shutong.ai.openai_compat import AiSettings, OpenAICompatProvider
from shutong.metadata.bangumi import BangumiSettings, BangumiSource
from shutong.metadata.base import MetadataSource
from shutong.net import make_opener, parse_proxy
from shutong.store.ai_calls import AiCallStore
from shutong.store.cache import CacheStore
from shutong.store.db import Database
from shutong.store.settings import SettingsStore


@dataclass(frozen=True)
class EngineConfig:
    ai_threshold: float = 0.85


@dataclass
class Services:
    db: Database
    source: MetadataSource
    ai: Optional[AuditedAi]
    config: EngineConfig


def _proxy_opener(settings: SettingsStore):
    try:
        return make_opener(parse_proxy(settings.get("network.proxy") or ""))
    except ValueError:  # stored before validation existed; go direct rather than fail every job
        return urlopen


def build_services(db: Database, *, opener=None, sleep=time.sleep) -> Services:
    """Bangumi goes through ``network.proxy``; AI only when ``ai.use_proxy`` is on. ``opener`` overrides both."""
    settings = SettingsStore(db)
    proxied = opener or _proxy_opener(settings)
    ai_opener = opener or (proxied if settings.get("ai.use_proxy") else urlopen)
    source = BangumiSource(
        BangumiSettings(base_url=settings.get("bangumi.base_url"), token=settings.get("bangumi.token") or None),
        CacheStore(db), opener=proxied, sleep=sleep,
    )
    ai = None
    base_url, api_key, model = (settings.get("ai.base_url"), settings.get("ai.api_key"), settings.get("ai.model"))
    if base_url and api_key and model:
        provider = OpenAICompatProvider(
            # A batch of a folder's names takes the model a while to answer.
            AiSettings(base_url=base_url, api_key=api_key, model=model,
                       threshold=settings.get("ai.threshold"), timeout=180),
            opener=ai_opener,
        )
        ai = AuditedAi(provider, AiCallStore(db))
    config = EngineConfig(ai_threshold=settings.get("ai.threshold"))
    return Services(db, source, ai, config)
