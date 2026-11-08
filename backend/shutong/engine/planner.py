"""Plan where each matched item goes and what metadata it gets, one scan batch at a time."""
from dataclasses import dataclass
from decimal import Decimal
import os
from pathlib import Path
import re
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple
import unicodedata

from shutong.engine.kinds.base import SourceEntry
from shutong.engine.kinds.manga.adapter import _volume_fields
from shutong.engine.kinds.manga.comicinfo import read_comic_info
from shutong.engine.kinds.manga.naming import build_output_name, parse_chapter, parse_volume
from shutong.engine.kinds.manga.volume import VolumeRef
from shutong.engine.kinds.novel.epub import read_metadata
from shutong.engine.kinds.novel.naming import (
    DEFAULT_VOLUME_PATTERN, NovelVolume, is_special_filename, natural_key, target_filename, volume_from_name,
)
from shutong.engine.metadata_build import bangumi_id, manga_metadata, metadata_to_json, novel_metadata
from shutong.engine.recognition import Directives, Recognition
from shutong.engine.states import ReviewReason
from shutong.engine.template import UNKNOWN_AUTHOR, render, uses_edition
from shutong.engine.text import path_safe
from shutong.metadata.base import Subject

_SP_NUMBER = re.compile(r"SP(\d+)", re.IGNORECASE)
_LIBRARY_NUMBER = re.compile(r"(?:Vol|Ch)\.(\d+)")
_LIBRARY_CHAPTERS = re.compile(r"Ch\.(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)")
_NOVEL_VOLUME = re.compile(DEFAULT_VOLUME_PATTERN)


@dataclass(frozen=True)
class PlanInput:
    item_id: int
    entry: SourceEntry
    recognition: Recognition
    subject: Subject
    output_suffix: str


@dataclass(frozen=True)
class PlanDecision:
    item_id: int
    status: str  # "planned" | "claimed" | "duplicate" | "review"
    review_reason: Optional[ReviewReason] = None
    series_name: Optional[str] = None
    target: Optional[Path] = None  # relative to the library directory
    metadata: Optional[dict] = None
    volume_key: Optional[str] = None
    note: str = ""
    fields: Optional[dict] = None  # the naming-template fields, kept so a new template can be previewed
    replaces: Optional[Path] = None  # the library file this one takes the place of
    source_mtime: Optional[float] = None


@dataclass
class _Draft:
    source: PlanInput
    series: str
    title: str
    width: int
    directives: Directives
    special_index: Optional[int] = None
    edition: Optional[str] = None  # in the series name: the template asks for the edition


def plan_batch(kind: str, library_dir: Path, template: str, inputs: Sequence[PlanInput], *,
               owner_of: Callable[[Path], Optional[int]] = lambda target: None,
               overwrite: str = "never", rename: bool = True,
               published: Mapping[Tuple[str, str], Path] = {},
               source_time: Callable[[Path], Optional[float]] = lambda target: None) -> List[PlanDecision]:
    """A series is named by its title alone unless the template uses ``{edition}``: then each edition is a
    series of its own (迷宫饭[bili电子版]), in its folder name and in the metadata media servers read.

    ``owner_of`` names the item a library file was published from: a file that came from another
    source is not this item's, however well its metadata matches.

    ``overwrite`` says what happens when the volume is already in the library: ``never`` keeps it, ``always``
    replaces it, ``larger`` and ``newer`` keep whichever file is bigger or more recent. ``source_time`` tells
    when a library file's source last changed (a file's own time is only when it was published).
    ``rename=False`` keeps the source's file name; ``published`` then finds volumes the names do not show.
    """
    library_dir = Path(library_dir)
    include_edition = kind == "manga" and uses_edition(template)
    drafts = [_draft(item, include_edition) for item in inputs]
    spellings = _existing_spellings(library_dir)
    for draft in drafts:
        # Land in the folder the library already has when only spacing / width / case differ.
        matches = spellings.get(_spelling_key(draft.series), [])
        if len(matches) == 1 and matches[0] != draft.series:
            draft.series = matches[0]
    if kind == "novel":
        _number_specials(library_dir, template, drafts)

    decisions: List[PlanDecision] = []
    taken: Dict[str, int] = {}
    batch_volumes: Dict[tuple, int] = {}
    first_volume = _first_volumes(library_dir, template, drafts) if kind == "novel" else {}
    shared_dirs = not _dir_is_per_series(template)
    for draft in drafts:
        item = draft.source
        parse = item.recognition.parse
        volume = parse.volume
        if volume is None:
            decisions.append(_review(item, ReviewReason.VOLUME, draft.series, "认不出卷号"))
            continue
        if kind == "novel" and volume.kind == "volume":
            group_key = (draft.series, volume.key())
            if group_key in batch_volumes:
                decisions.append(_review(item, ReviewReason.VOLUME, draft.series, "同一批里卷号重复"))
                continue
            batch_volumes[group_key] = item.item_id
        if kind == "manga" and not draft.directives.width:
            # Follow the digits the series' files already use (Ch.002 stays Ch.003), else 2 / 4 for chapters.
            existing = _library_width(_series_dir(library_dir, template, draft), volume.kind)
            draft.width = existing or (4 if volume.kind == "chapter" else 2)
        fields = _fields(kind, draft, volume, item)
        target = render(template, fields)
        if not rename:
            target = target.with_name(_original_name(item))
        final = library_dir / target
        directives = draft.directives
        if kind == "manga":
            metadata = manga_metadata(draft.series, volume, item.subject, directives, draft.width)
        else:
            fallback = unicodedata.normalize("NFC", item.entry.path.stem)
            metadata = novel_metadata(draft.series, volume, item.subject, parse.details, directives,
                                      first_volume=first_volume.get(item.item_id, False), fallback_title=fallback)
        folded = target.as_posix().casefold()
        planned_fields = dict(metadata=metadata_to_json(metadata), volume_key=volume.key(), fields=fields,
                              source_mtime=_mtime(item.entry.path))
        same_volume = _same_volume(kind, library_dir, final, volume, draft.series if shared_dirs else None, draft, published)
        current = same_volume or (final if os.path.lexists(final) else None)
        owner = owner_of(target)
        if overwrite != "never" and current is not None and current.is_file() and folded not in taken \
                and owner != item.item_id:
            kept = _keep_reason(overwrite, item.entry.path, current, source_time(current.relative_to(library_dir)))
            if kept is None:
                taken[folded] = item.item_id
                decisions.append(PlanDecision(item.item_id, "planned", None, draft.series, target,
                                              replaces=current.relative_to(library_dir), **planned_fields))
                continue
            if owner is not None or not _existing_matches(kind, final, draft.series, volume, metadata):
                decisions.append(PlanDecision(item.item_id, "duplicate", None, draft.series, target, None, volume.key(), kept))
                continue
        if not include_edition and item.recognition.parse.edition and os.path.lexists(final):
            # Without the edition in the name, the file there may be another edition of this volume.
            decisions.append(_review(item, ReviewReason.CONFLICT, draft.series,
                                     "目标位置已被占用（可能是另一个版本）"))
            continue
        if folded not in taken and owner in (None, item.item_id) \
                and _existing_matches(kind, final, draft.series, volume, metadata):
            taken[folded] = item.item_id
            decisions.append(PlanDecision(item.item_id, "claimed", None, draft.series, target,
                                          metadata_to_json(metadata), volume.key(),
                                          "库里的文件就是这一卷，直接认领", fields))
            continue
        if same_volume is not None:
            decisions.append(PlanDecision(item.item_id, "duplicate", None, draft.series, target, None,
                                          volume.key(), "库里已经有这一卷"))
            continue
        if os.path.lexists(final) or folded in taken:
            decisions.append(_review(item, ReviewReason.CONFLICT, draft.series, "目标位置已被占用"))
            continue
        taken[folded] = item.item_id
        decisions.append(PlanDecision(item.item_id, "planned", None, draft.series, target, **planned_fields))
    return decisions


def _original_name(item: PlanInput) -> str:
    path = item.entry.path
    stem = path.name if path.is_dir() else path.stem
    return unicodedata.normalize("NFC", stem).rstrip(" .") + item.output_suffix


def _mtime(path: Path) -> Optional[float]:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _size(path: Path) -> int:
    if path.is_dir():
        return sum(entry.stat().st_size for entry in path.rglob("*") if entry.is_file())
    return path.stat().st_size


def _same_volume(kind: str, library_dir: Path, final: Path, volume, series: Optional[str], draft: _Draft,
                 published: Mapping[Tuple[str, str], Path]) -> Optional[Path]:
    """The file that already holds this volume, by its name in the series folder or by the records."""
    found = _volume_file(kind, final.parent, volume, series)
    if found is not None:
        return found
    recorded = published.get((draft.series, volume.key())) if volume.kind != "special" else None
    if recorded is not None and os.path.lexists(library_dir / recorded):
        return library_dir / recorded
    return None


def _keep_reason(overwrite: str, source: Path, current: Path, current_time: Optional[float]) -> Optional[str]:
    """Why the library's file stays; None when the new one takes its place."""
    if overwrite == "always":
        return None
    try:
        if overwrite == "larger":
            return None if _size(source) > current.stat().st_size else "库里的文件不比它小，保留库里的"
        known = current_time if current_time is not None else current.stat().st_mtime
        return None if source.stat().st_mtime > known else "库里的文件不比它旧，保留库里的"
    except OSError:
        return "比较不了文件，保留库里的"


def _draft(item: PlanInput, include_edition: bool = False) -> _Draft:
    parse = item.recognition.parse
    title = parse.title_hint
    edition = parse.edition if include_edition else None
    series = build_output_name(title, edition)
    directives = item.recognition.directives
    return _Draft(item, series, title, directives.width or 2, directives, edition=edition)


_EDITION_SUFFIX = re.compile(r"\[[^\[\]]*\]$")


def _series_title(draft: "_Draft") -> str:
    """``{series}`` in a template: the series name without the edition, which ``{edition}`` adds where wanted."""
    return _EDITION_SUFFIX.sub("", draft.series) if draft.edition else draft.series


def _author(item: PlanInput) -> str:
    writers = [writer.strip() for writer in item.subject.writers if writer and writer.strip()]
    return path_safe(writers[0]) if writers else UNKNOWN_AUTHOR


def _spelling_key(name: str) -> str:
    return "".join(unicodedata.normalize("NFKC", name).casefold().split())


def _existing_spellings(library_dir: Path) -> Dict[str, List[str]]:
    spellings: Dict[str, List[str]] = {}
    try:
        entries = [entry for entry in os.scandir(library_dir) if entry.is_dir() and not entry.name.startswith(".")]
    except FileNotFoundError:
        return spellings
    for entry in entries:
        name = unicodedata.normalize("NFC", entry.name)
        spellings.setdefault(_spelling_key(name), []).append(name)
    return spellings


def _review(item: PlanInput, reason: ReviewReason, series: Optional[str], note: str) -> PlanDecision:
    return PlanDecision(item.item_id, "review", reason, series, None, None,
                        item.recognition.parse.volume.key() if item.recognition.parse.volume else None, note)


def _fields(kind: str, draft: _Draft, volume, item: PlanInput) -> Dict[str, Optional[str]]:
    if kind == "manga":
        volume_text = volume.token(draft.width)
    else:
        name = target_filename(draft.series, volume, draft.width, draft.special_index)
        volume_text = name[len(draft.series) + 1: -len(".epub")]
    release = item.subject.release_date or ""
    return {
        "series": _series_title(draft),
        "author": _author(item),
        "title": draft.title,
        "edition": item.recognition.parse.edition,
        "volume": volume_text,
        "year": release[:4] if release[:4].isdigit() else None,
        "bgm": bangumi_id(item.subject),
        "ext": item.output_suffix,
    }


def _series_dir(library_dir: Path, template: str, draft: _Draft) -> Path:
    fields = {"series": _series_title(draft), "author": _author(draft.source),
              "title": draft.title, "edition": draft.source.recognition.parse.edition,
              "volume": "SP00", "ext": draft.source.output_suffix,
              "bgm": bangumi_id(draft.source.subject),
              "year": None}
    return (library_dir / render(template, fields)).parent


def _number_specials(library_dir: Path, template: str, drafts: List[_Draft]) -> None:
    by_series: Dict[str, List[_Draft]] = {}
    for draft in drafts:
        volume = draft.source.recognition.parse.volume
        if isinstance(volume, NovelVolume) and volume.kind == "special":
            by_series.setdefault(draft.series, []).append(draft)
    for series, specials in by_series.items():
        directory = _series_dir(library_dir, template, specials[0])
        used = [int(m.group(1)) for name in _names(directory)
                if is_special_filename(name) for m in [_SP_NUMBER.search(name)] if m]
        next_index = max(used, default=0) + 1
        for draft in sorted(specials, key=lambda d: natural_key(unicodedata.normalize("NFC", d.source.entry.path.name))):
            draft.special_index = next_index
            next_index += 1


def _first_volumes(library_dir: Path, template: str, drafts: List[_Draft]) -> Dict[int, bool]:
    """The smallest batch volume of a series gets the summary, unless the library already has volumes."""
    lowest: Dict[str, _Draft] = {}
    for draft in drafts:
        volume = draft.source.recognition.parse.volume
        if isinstance(volume, NovelVolume) and volume.kind == "volume":
            current = lowest.get(draft.series)
            if current is None or volume.number < current.source.recognition.parse.volume.number:
                lowest[draft.series] = draft
    result = {}
    for series, draft in lowest.items():
        existing = [name for name in _names(_series_dir(library_dir, template, draft))
                    if name.casefold().endswith(".epub") and not is_special_filename(name)]
        result[draft.source.item_id] = not existing
    return result


def _library_width(directory: Path, volume_kind: str) -> Optional[int]:
    """The most common digit count of ``Vol.``/``Ch.`` numbers already in the series folder."""
    prefix = "Ch." if volume_kind == "chapter" else "Vol."
    counts: Dict[int, int] = {}
    for name in _names(directory):
        match = _LIBRARY_NUMBER.search(name)
        if match and match.group(0).startswith(prefix):
            counts[len(match.group(1))] = counts.get(len(match.group(1)), 0) + 1
    return max(counts, key=lambda width: (counts[width], width)) if counts else None


def _existing_matches(kind: str, final: Path, series: str, volume, metadata) -> bool:
    """Is the file already at the target this very series and volume (so it can be claimed)?"""
    if not final.is_file():
        return False
    try:
        if kind == "manga":
            fields = read_comic_info(final)
            return fields.get("Series") == series and all(
                fields.get(tag) == expected for tag, expected in _volume_fields(volume).items())
        existing = read_metadata(final)
        return existing.series == series and existing.series_index == str(metadata.series_index)
    except Exception:  # unreadable or foreign file: never claim it
        return False


def _dir_is_per_series(template: str) -> bool:
    """Does the template put each series in its own directory?"""
    def parent(series: str) -> Path:
        return render(template, {"series": series, "title": series, "author": "a", "edition": "e", "volume": "Vol.01",
                                 "ext": ".x"}).parent
    return parent("a") != parent("b")


def _volume_file(kind: str, directory: Path, volume, series: Optional[str] = None) -> Optional[Path]:
    """Same volume already in the target directory; with a shared directory it must be the same series too."""
    key = volume.key()
    if kind == "novel" and volume.kind == "special":
        return None  # specials always get a fresh SP number
    if volume.kind == "special" and volume.label:
        return None  # told apart by the label; a file of the very same name is a conflict, not this volume
    for name in _names(directory):
        if series is not None and not name.casefold().startswith(series.casefold()):
            continue
        if kind == "manga":
            chapters = _LIBRARY_CHAPTERS.search(name)
            if chapters:
                found = VolumeRef.chapter(Decimal(chapters.group(1)), Decimal(chapters.group(2)))
            else:
                found = parse_volume(name) or parse_chapter(name)
            if found is not None and found.key() == key:
                return directory / name
        else:
            stem = name[: -len(".epub")] if name.casefold().endswith(".epub") else None
            if stem is None or is_special_filename(name):
                continue
            try:
                number = volume_from_name(stem, _NOVEL_VOLUME)
            except ValueError:
                continue
            if number is not None and NovelVolume.volume(number).key() == key:
                return directory / name
    return None


def _names(directory: Path) -> List[str]:
    try:
        return [unicodedata.normalize("NFC", entry.name) for entry in os.scandir(directory)
                if not entry.name.startswith(".")]
    except (FileNotFoundError, NotADirectoryError):
        return []
