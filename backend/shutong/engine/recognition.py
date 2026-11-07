"""What the organizer knows about one source after recognition, and the output options planning uses."""
from dataclasses import dataclass, field
from typing import Optional

from shutong.engine.kinds.base import ParseResult


@dataclass(frozen=True)
class Directives:
    """Output options for a series; every one has a sensible default."""

    width: Optional[int] = None  # digits in volume numbers; None: follow the library, else 2 (4 for chapters)
    lang: Optional[str] = None
    direction: Optional[str] = None


@dataclass(frozen=True)
class Recognition:
    parse: ParseResult
    directives: Directives = field(default_factory=Directives)
