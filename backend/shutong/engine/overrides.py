"""Volume numbers typed by a person in review: ``13``, ``1.5``, ``01-05``, ``SP1``, ``Ch.15`` / ``第15话``."""
from decimal import Decimal
import re

from shutong.engine.kinds.manga.volume import VolumeRef
from shutong.engine.kinds.novel.naming import NovelVolume

_VOLUME = re.compile(r"^(\d+(?:\.\d+)?)$")
_RANGE = re.compile(r"^(\d+)\s*-\s*(\d+)$")
_SPECIAL = re.compile(r"^sp\s*0*(\d+)$", re.IGNORECASE)
_CHAPTER = re.compile(r"^(?:ch\.?\s*(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?"
                      r"|第?\s*(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?\s*[话話])$", re.IGNORECASE)


def parse_volume_text(text: str) -> VolumeRef:
    value = str(text).strip()
    match = _VOLUME.match(value)
    if match:
        return VolumeRef.volume(Decimal(match.group(1)))
    match = _RANGE.match(value)
    if match and int(match.group(1)) < int(match.group(2)):
        return VolumeRef.range(Decimal(int(match.group(1))), Decimal(int(match.group(2))))
    match = _SPECIAL.match(value)
    if match:
        return VolumeRef.special(int(match.group(1)))
    match = _CHAPTER.match(value)
    if match:
        start, end = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
        return VolumeRef.chapter(Decimal(start), Decimal(end) if end else None)
    raise ValueError("无法识别的卷号：{0}".format(text))


def parse_volume_for(kind: str, text: str):
    """What the planner of this kind of library expects: a novel volume is a number or a special, nothing else."""
    volume = parse_volume_text(text)
    if kind != "novel":
        return volume
    if volume.kind == "volume":
        return NovelVolume.volume(volume.start)
    if volume.kind == "special":
        return NovelVolume.special()  # the planner gives it the next free SP number
    raise ValueError("轻小说的卷号只能写 13、1.5 或 SP1：{0}".format(text))
