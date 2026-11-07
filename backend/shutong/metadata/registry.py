"""Which metadata sources are switched on, and in what order they are asked."""
from typing import Dict, Mapping, Sequence, Tuple

from .base import MetadataSource

KNOWN_SOURCES = ("bangumi", "anilist")
LABELS = {"bangumi": "Bangumi", "anilist": "AniList"}
DEFAULT_ENABLED = ("bangumi",)


class SourceRegistry:
    def __init__(self, sources: Mapping[str, MetadataSource], enabled) -> None:
        self._sources: Dict[str, MetadataSource] = dict(sources)
        names = enabled if isinstance(enabled, (list, tuple)) else ()
        chosen = [name for name in dict.fromkeys(names) if isinstance(name, str) and name in self._sources]
        if not chosen:  # nothing usable stored: fall back rather than organize without any source
            chosen = [name for name in DEFAULT_ENABLED if name in self._sources] or list(self._sources)[:1]
        self._enabled = tuple(self._sources[name] for name in chosen)

    @classmethod
    def single(cls, source: MetadataSource) -> "SourceRegistry":
        return cls({source.name: source}, [source.name])

    @property
    def enabled(self) -> Tuple[MetadataSource, ...]:
        return self._enabled

    @property
    def primary(self) -> MetadataSource:
        return self._enabled[0]

    @property
    def names(self) -> Tuple[str, ...]:
        """Every source built, enabled or not."""
        return tuple(self._sources)

    def get(self, name: str) -> MetadataSource:
        """Any source built, switched on or not: items organized from it can still be refreshed."""
        return self._sources[name]
