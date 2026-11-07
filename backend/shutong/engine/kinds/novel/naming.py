"""Light novel names: the files the library uses, and reading their volume numbers back."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import Optional
import unicodedata


DEFAULT_VOLUME_PATTERN = r"(?i)(?<![A-Za-z0-9])Vol\.?\s*0*(\d+(?:\.\d+)?)(?![0-9])"

_ROMAN_VALUES = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}
_ROMAN_TOKEN = re.compile(r"^[IVXLCDM]+$")


def volume_from_name(
    stem: str, pattern: "re.Pattern[str]"
) -> Optional[Decimal]:
    """Return the first captured volume number from a file stem.

    Every capture group is tried in order so a policy can combine several
    filename shapes (``Vol.3`` / ``[03]`` / ``第3卷``) in one regex. Decimals
    (``7.5``) and the volume ``0`` are valid; Roman numerals are converted.
    """
    match = pattern.search(stem)
    if not match:
        return None
    for group in match.groups():
        token = (group or "").strip()
        if not token:
            continue
        volume = _parse_volume_token(token)
        if volume is not None:
            return volume
    raise ValueError("volume pattern captured no usable volume number")


def _parse_volume_token(token: str) -> Optional[Decimal]:
    try:
        volume = Decimal(token)
    except InvalidOperation:
        roman = roman_to_int(token)
        if roman is None:
            raise ValueError(
                "volume pattern captured non-numeric value {0!r}".format(token)
            )
        volume = Decimal(roman)
    if not volume.is_finite():
        raise ValueError("volume pattern captured a non-finite value {0!r}".format(token))
    if volume < 0:
        raise ValueError("volume pattern captured a negative volume")
    return volume


def roman_to_int(value: str) -> Optional[int]:
    """Convert an ASCII or full-width Roman numeral such as ``XIV`` to an int."""
    text = unicodedata.normalize("NFKC", value).upper()
    if not text or not _ROMAN_TOKEN.match(text):
        return None
    total = 0
    previous = 0
    for character in reversed(text):
        current = _ROMAN_VALUES[character]
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    return total if 0 < total < 4000 else None


def format_volume(volume: Decimal) -> str:
    """Render a decimal volume without a trailing ``.0``."""
    if volume == volume.to_integral_value():
        return str(int(volume))
    text = format(volume, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def volume_filename(output_name: str, volume: Decimal, width: int) -> str:
    integral = int(volume)
    token = str(integral).zfill(width)
    fraction = volume - integral
    if fraction:
        digits = format(fraction, "f").split(".", 1)[1].rstrip("0")
        token = "{0}.{1}".format(token, digits)
    return "{0} Vol.{1}.epub".format(output_name, token)


def special_filename(output_name: str, special_index: int) -> str:
    return "{0} SP{1}.epub".format(output_name, str(special_index).zfill(2))


def natural_key(value: str):
    """Sort key that orders embedded integers numerically and safely."""
    return [
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", value)
    ]


def is_special_filename(filename: str) -> bool:
    return bool(re.search(r"SP\d+", Path(filename).name, re.IGNORECASE))


@dataclass(frozen=True)
class NovelVolume:
    """A numbered volume, or a special whose SP index the planner assigns per series."""

    kind: str  # "volume" | "special"
    number: Optional[Decimal] = None

    @classmethod
    def volume(cls, number: Decimal) -> "NovelVolume":
        return cls("volume", Decimal(number))

    @classmethod
    def special(cls) -> "NovelVolume":
        return cls("special")

    def key(self) -> str:
        if self.kind == "special":
            return "special"
        return "volume:{0}".format(format_volume(self.number))


def target_filename(
    output_name: str,
    volume: NovelVolume,
    width: int = 2,
    special_index: Optional[int] = None,
) -> str:
    if volume.kind == "special":
        if special_index is None:
            raise ValueError("a special needs its series-wide SP index")
        return special_filename(output_name, special_index)
    return volume_filename(output_name, volume.number, width)
