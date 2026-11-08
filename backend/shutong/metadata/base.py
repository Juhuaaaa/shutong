"""Metadata source interface and the normalized subject every source returns."""
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Tuple


class MetadataUnavailable(Exception):
    """The source is temporarily unreachable (retries exhausted); try again later."""


_WEB_URLS = {
    "bangumi": "https://bgm.tv/subject/{0}",
    "anilist": "https://anilist.co/manga/{0}",
}


def web_url_for(source: str, subject_id: str) -> str:
    """The public page of a subject, which Kavita links to; empty when the source has no pages."""
    template = _WEB_URLS.get(source)
    return template.format(subject_id) if template and str(subject_id or "").strip() else ""


def subject_web_url(subject_id) -> str:
    """The public bgm.tv page of a Bangumi subject."""
    return web_url_for("bangumi", str(subject_id))


@dataclass(frozen=True)
class SubjectRef:
    """Which source a subject comes from, and its id there (ids are text: some sources use UUIDs)."""
    source: str
    id: str

    @property
    def key(self) -> str:
        return "{0}:{1}".format(self.source, self.id)

    def to_json(self) -> dict:
        return {"source": self.source, "id": self.id}

    @classmethod
    def from_json(cls, value: Any) -> "SubjectRef":
        if not isinstance(value, Mapping):
            raise ValueError("条目要写成 {source, id}")
        source, subject_id = value.get("source"), value.get("id")
        if isinstance(subject_id, bool) or not isinstance(source, str) or not source.strip() \
                or not isinstance(subject_id, (str, int)) or not str(subject_id).strip():
            raise ValueError("条目的来源和编号都不能为空")
        return cls(source.strip(), str(subject_id).strip())

    @classmethod
    def from_overrides(cls, overrides: Mapping) -> Optional["SubjectRef"]:
        """The subject chosen for an item; ``bgm`` is how choices were kept before there were other sources."""
        if overrides.get("subject"):
            return cls.from_json(overrides["subject"])
        bgm = overrides.get("bgm")
        if bgm is None or bgm == "":
            return None
        return cls("bangumi", str(bgm))


@dataclass(frozen=True)
class Subject:
    subject_id: str
    name: str
    name_cn: str
    summary: str
    release_date: Optional[str]
    writers: Tuple[str, ...]
    publisher: str
    genres: Tuple[str, ...]
    completed: bool
    total_volumes: Optional[int]
    # Book platform, e.g. "小说" or "漫画"; empty when the source omits it.
    platform: str = ""
    source: str = "bangumi"
    # A series entry (True), a single book such as one tankobon or a one-shot (False); None when the source
    # does not say.
    series: Optional[bool] = None
    # Other names (English, romanized, synonyms), best first: shown when there is no Chinese name.
    aliases: Tuple[str, ...] = ()
    image: str = ""
    # Illustrators of a light novel, kept apart from the writers.
    illustrators: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.subject_id, str):
            object.__setattr__(self, "subject_id", "" if self.subject_id is None else str(self.subject_id))

    @property
    def display_title(self) -> str:
        return self.name_cn or (self.aliases[0] if self.aliases else "") or self.name

    @property
    def ref(self) -> SubjectRef:
        return SubjectRef(self.source, self.subject_id)

    @property
    def web_url(self) -> str:
        return web_url_for(self.source, self.subject_id)

    @classmethod
    def unlisted(cls, title: str) -> "Subject":
        """A series no source has: organized under the AI's title, without metadata."""
        return cls(subject_id="", name=title, name_cn=title, summary="", release_date=None, writers=(),
                   publisher="", genres=(), completed=False, total_volumes=None, source="none")


class MetadataSource(Protocol):
    name: str
    label: str

    def search(self, query: str, kind: str) -> Tuple[Subject, ...]: ...

    def get(self, subject_id: str, *, fresh: bool = False) -> Subject: ...
