"""Volume references for manga: a single volume, a range, a special, or a chapter."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class VolumeRef:
    kind: str
    start: Optional[Decimal] = None
    end: Optional[Decimal] = None
    special_number: Optional[int] = None
    label: str = ""

    @classmethod
    def volume(cls, value: Decimal) -> "VolumeRef":
        return cls(kind="volume", start=value)

    @classmethod
    def range(cls, start: Decimal, end: Decimal) -> "VolumeRef":
        return cls(kind="range", start=start, end=end)

    @classmethod
    def chapter(cls, value: Decimal, end: Optional[Decimal] = None) -> "VolumeRef":
        """A chapter with no volume (webtoons, serialized releases); Kavita shows it as a loose chapter.

        ``end`` makes it a run of chapters in one file (``Ch.0001-0040``).
        """
        return cls(kind="chapter", start=value, end=end if end is not None and end > value else None)

    @classmethod
    def special(cls, number: int, label: str = "") -> "VolumeRef":
        return cls(kind="special", special_number=number, label=label)

    def key(self) -> str:
        if self.kind == "volume":
            return "volume:{0}".format(canonical_decimal(self.start))
        if self.kind == "chapter":
            if self.end is not None:
                return "chapter:{0}-{1}".format(canonical_decimal(self.start), canonical_decimal(self.end))
            return "chapter:{0}".format(canonical_decimal(self.start))
        if self.kind == "range":
            return "range:{0}-{1}".format(
                canonical_decimal(self.start), canonical_decimal(self.end)
            )
        return "special:{0}".format(self.special_number)

    def token(self, width: int) -> str:
        if self.kind == "special":
            suffix = " {0}".format(self.label) if self.label else ""
            return "SP{0:02d}{1}".format(self.special_number, suffix)
        start = format_decimal(self.start, width)
        if self.kind == "chapter":
            if self.end is not None:
                return "Ch.{0}-{1}".format(start, format_decimal(self.end, width))
            return "Ch.{0}".format(start)
        if self.kind == "range":
            return "Vol.{0}-{1}".format(start, format_decimal(self.end, width))
        return "Vol.{0}".format(start)


def format_decimal(value: Decimal, width: int) -> str:
    text = format(value, "f")
    whole, dot, fraction = text.partition(".")
    padded = whole.zfill(width)
    fraction = fraction.rstrip("0")
    return "{0}.{1}".format(padded, fraction) if dot and fraction else padded


def canonical_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text
