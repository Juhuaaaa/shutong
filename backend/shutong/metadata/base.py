"""Metadata source interface and the normalized subject every source returns."""
from dataclasses import dataclass
from typing import Optional, Protocol, Tuple


class MetadataUnavailable(Exception):
    """The source is temporarily unreachable (retries exhausted); try again later."""


def subject_web_url(subject_id: int) -> str:
    """The public bgm.tv page Kavita links to from a series."""
    return "https://bgm.tv/subject/{0}".format(subject_id)


@dataclass(frozen=True)
class Subject:
    subject_id: int
    name: str
    name_cn: str
    summary: str
    release_date: Optional[str]
    writers: Tuple[str, ...]
    publisher: str
    genres: Tuple[str, ...]
    completed: bool
    total_volumes: Optional[int]
    # Bangumi book platform, e.g. "小说" or "漫画"; empty when the API omits it.
    platform: str = ""
    source: str = "bangumi"
    # Bangumi's book "series" flag: True for a series entry, False for a single book (one tankobon or a
    # one-shot); None when the source does not say.
    series: Optional[bool] = None

    @property
    def display_title(self) -> str:
        return self.name_cn or self.name

    @property
    def web_url(self) -> str:
        return subject_web_url(self.subject_id) if self.subject_id > 0 else ""

    @classmethod
    def unlisted(cls, title: str) -> "Subject":
        """A series Bangumi does not have: organized under the AI's title, without metadata."""
        return cls(subject_id=0, name=title, name_cn=title, summary="", release_date=None, writers=(),
                   publisher="", genres=(), completed=False, total_volumes=None, source="none")


class MetadataSource(Protocol):
    name: str

    def search(self, query: str, kind: str) -> Tuple[Subject, ...]: ...

    def get(self, subject_id: int) -> Subject: ...
