"""Wire the metadata source, AI and engine options from stored settings."""
from dataclasses import dataclass
import time
from typing import Optional
from urllib.request import urlopen

from shutong.ai.audit import AuditedAi
from shutong.ai.openai_compat import AiSettings, OpenAICompatProvider
from shutong.metadata.anilist import AniListSource
from shutong.metadata.bangumi import DEFAULT_BASE_URL, BangumiSettings, BangumiSource
from shutong.metadata.registry import SourceRegistry
from shutong.net import make_opener, parse_proxy
from shutong.store.ai_calls import AiCallStore
from shutong.store.cache import CacheStore
from shutong.store.db import Database
from shutong.store.settings import SettingsStore


@dataclass(frozen=True)
class EngineConfig:
    ai_threshold: float = 0.85
    translate_summaries: bool = False  # English (AniList) summaries in Chinese, by the AI


@dataclass
class Services:
    db: Database
    sources: SourceRegistry
    ai: Optional[AuditedAi]
    config: EngineConfig

    def __post_init__(self) -> None:
        if not isinstance(self.sources, SourceRegistry):  # one source given directly (tests, offline demos)
            self.sources = SourceRegistry.single(self.sources)


def _proxy_opener(settings: SettingsStore):
    try:
        return make_opener(parse_proxy(settings.get("network.proxy") or ""))
    except ValueError:  # stored before validation existed; go direct rather than fail every job
        return urlopen


def _address(value) -> str:
    return (value or "").strip().rstrip("/")


def bangumi_image_base(settings: SettingsStore) -> str:
    """Where Bangumi covers come from: their own setting, else the API's address (a mirror usually serves both)."""
    return (_address(settings.get("bangumi.image_base_url")) or _address(settings.get("bangumi.base_url"))
            or DEFAULT_BASE_URL)


def build_services(db: Database, *, opener=None, sleep=time.sleep) -> Services:
    """Metadata sources go through ``network.proxy``; AI only when ``ai.use_proxy`` is on. ``opener`` overrides both."""
    settings = SettingsStore(db)
    proxied = opener or _proxy_opener(settings)
    ai_opener = opener or (proxied if settings.get("ai.use_proxy") else urlopen)
    base_url = _address(settings.get("bangumi.base_url")) or DEFAULT_BASE_URL
    bangumi = BangumiSource(
        BangumiSettings(base_url=base_url, token=settings.get("bangumi.token") or None,
                        image_base_url=bangumi_image_base(settings)),
        CacheStore(db), opener=proxied, sleep=sleep,
    )
    anilist = AniListSource(CacheStore(db), opener=proxied, sleep=sleep)
    sources = SourceRegistry({"bangumi": bangumi, "anilist": anilist}, settings.get("metadata.sources"))
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
    config = EngineConfig(ai_threshold=settings.get("ai.threshold"),
                          translate_summaries=bool(settings.get("metadata.translate_summaries")))
    return Services(db, sources, ai, config)
