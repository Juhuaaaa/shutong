"""The media server boundary (spec §7.7): what the engine needs after publishing."""
from dataclasses import dataclass
from typing import List, Protocol


class ServerError(RuntimeError):
    """A media server problem, in words for the user (never containing the password)."""


@dataclass(frozen=True)
class ServerLibrary:
    id: str  # Kavita numbers are kept as text too
    name: str


class MediaServer(Protocol):
    def test(self) -> None: ...

    def libraries(self) -> List[ServerLibrary]: ...

    def scan_library(self, library_id: str) -> None: ...

    def refresh_series(self, library_id: str, series_name: str) -> bool: ...
