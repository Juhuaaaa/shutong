"""The one entry point that drives items through the pipeline.

scan: discover → dedupe by fingerprint → AI reads each folder's names → match → plan.
Items end in PLANNED (published right after by the caller), DUPLICATE, NEEDS_REVIEW (the AI
was unsure), PARSED (AI or metadata source unreachable; redone on the next scan) or FAILED.
Every failure lands on one item; a scan never aborts halfway.
"""
from dataclasses import replace
from decimal import Decimal
import logging
import os
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple
import unicodedata

from shutong.engine.ai_assist import SourceContext, _effective_threshold, _safe_name
from shutong.engine.ai_recognize import AiNotConfigured, FileReading, Reading, SeriesReading, batches, read_batch
from shutong.engine.disposal import DisposalContext, dispose_source, remove_tree
from shutong.engine import failure
from shutong.engine.fingerprint import fingerprint
from shutong.engine.kinds.base import KindAdapter, ParseResult, SourceEntry
from shutong.engine.kinds.manga.adapter import MangaAdapter
from shutong.engine.kinds.novel.adapter import NovelAdapter, NovelPlan
from shutong.engine.match import find_own_entry, label_of, match_across, match_subject
from shutong.engine import covers
from shutong.engine.metadata_build import metadata_from_json, metadata_to_json
from shutong.engine.metadata_edit import ManualMetadata, apply_manual, apply_subject, rewrite_cbz, rewrite_epub
from shutong.engine.overrides import parse_volume_for, parse_volume_text
from shutong.engine.planner import PlanInput, plan_batch
from shutong.engine.publish import STATE_DIR, Publisher, TargetExists
from shutong.engine.recognition import Recognition
from shutong.engine.states import TRANSITIONS, ItemStatus, ReviewReason
from shutong.engine.template import DEFAULT_TEMPLATE
from shutong.metadata.base import Subject, SubjectRef
from shutong.services import Services
from shutong.store.ai_calls import AiCallStore
from shutong.store.journal import JournalStore
from shutong.store.records import Item, ItemStore, Library, LibraryStore, RunStore

log = logging.getLogger("shutong.organize")


_RESUMABLE = frozenset({ItemStatus.DISCOVERED, ItemStatus.PARSED, ItemStatus.MATCHED})
# Cancelled by the organizer because the source went missing or changed (not by the user): a scan that
# finds the same bytes again picks the item up.
_SOURCE_GONE = frozenset({"source_missing", "source_changed"})
_CONFIRMABLE = frozenset({ItemStatus.NEEDS_REVIEW, ItemStatus.DUPLICATE, ItemStatus.FAILED, ItemStatus.PARSED,
                          ItemStatus.CANCELLED})


class LibraryUnavailable(RuntimeError):
    """The source or library directory is missing (e.g. an SMB share is not mounted)."""


def require_directories(library: Library) -> None:
    for label, directory in (("source", library.source_dir), ("library", library.library_dir)):
        if not Path(directory).is_dir():
            raise LibraryUnavailable("{0} directory of {1} is not available: {2}".format(
                label, library.name, directory))


def adapter_for(library: Library) -> KindAdapter:
    if library.kind == "manga":
        return MangaAdapter(pdf_to_cbz=library.pdf_to_cbz)
    return NovelAdapter()


_AI_FAILURE_LIMIT = 3  # a scan stops asking an AI it could not reach this many times in a row
_NO_READING = Reading()


class Organizer:
    def __init__(self, services: Services) -> None:
        self.services = services
        db = services.db
        self.libraries = LibraryStore(db)
        self.runs = RunStore(db)
        self.items = ItemStore(db)
        self.ai_calls = AiCallStore(db)
        # AI answers for the current run, keyed by source path; one call per batch of a folder's names.
        self._readings: Dict[str, Reading] = {}
        # Subject choices for the current run, keyed by source folder: one call per series, not per volume.
        self._ai_memo: Dict[tuple, object] = {}
        # The series each folder's first confident answer named, kept for its later batches and retries.
        self._settled: Dict[Optional[str], List[SeriesReading]] = {}
        self._ai_failures = 0  # calls in a row that could not reach the AI
        # The metadata source each series folder was organized from: its later files stay with that source.
        self._folder_sources: Dict[Tuple[int, Optional[Path], str], str] = {}
        self._folder_sources_loaded: set = set()
        # Asked between folders and files: a job being cancelled stops at the next one.
        self.should_stop: Callable[[], bool] = lambda: False
        # Told how far a scan is: {"done": files settled, "total": files found, "current": folder}.
        self.on_progress: Optional[Callable[[dict], None]] = None
        self._progress = {"done": 0, "total": 0, "current": None}

    def _report(self, **changes) -> None:
        self._progress.update(changes)
        if self.on_progress is not None:
            self.on_progress(dict(self._progress))

    def _advance(self, count: int = 1) -> None:
        if count:
            self._report(done=self._progress["done"] + count)

    def expect(self, count: int) -> None:
        """More files to settle in this job than the scan found (an earlier run's leftovers)."""
        if count:
            self._report(total=self._progress["total"] + count, current=None)

    # ---- scan -----------------------------------------------------------------------------

    def scan(self, library_id: int, trigger: str = "manual",
             on_planned: Optional[Callable[[List[int]], None]] = None) -> int:
        """Discover, recognise and plan one source folder at a time.

        ``on_planned`` gets each folder's planned items as soon as they are planned (the API publishes them
        right away), so a folder is organised before the next one is even discovered.
        """
        library = self.libraries.get(library_id)
        require_directories(library)
        if self.services.ai is None:
            raise AiNotConfigured()
        adapter = adapter_for(library)
        return self._scan_entries(library, adapter, adapter.scan(library.source_dir).entries, trigger, on_planned)

    def scan_paths(self, library_id: int, entries: Sequence[SourceEntry],
                   on_planned: Optional[Callable[[List[int]], None]] = None) -> int:
        """Like :meth:`scan`, for what :func:`~shutong.engine.dropped.resolve_drops` found."""
        library = self.libraries.get(library_id)
        require_directories(library)
        if self.services.ai is None:
            raise AiNotConfigured()
        return self._scan_entries(library, adapter_for(library), entries, "drop", on_planned)

    def _scan_entries(self, library: Library, adapter: KindAdapter, entries: Sequence[SourceEntry], trigger: str,
                      on_planned: Optional[Callable[[List[int]], None]]) -> int:
        library_id = library.id
        run_id = self.runs.create(library_id, trigger)
        self._reset()
        folders: Dict[Optional[str], List[SourceEntry]] = {}
        for entry in entries:
            folders.setdefault(entry.series_folder, []).append(entry)
        self._report(done=0, total=sum(len(entries) for entries in folders.values()), current=None)
        known = 0
        everything: List[int] = []
        seen = set()

        def settle(todo: List[Tuple[int, SourceEntry]]) -> List[Tuple[int, SourceEntry]]:
            """Recognise, plan and publish; returns the files still waiting for the AI."""
            self._prepare(library, adapter, todo)
            matched: List[PlanInput] = []
            for item_id, entry in todo:
                planned = self._process(item_id, library, adapter, entry)
                if planned is not None:
                    matched.append(planned)
            self._plan(library, matched)
            waiting = [pair for pair in todo if self._readings.get(str(pair[1].path), _NO_READING).retry]
            ids = [item_id for item_id, _ in todo]
            ready = [item_id for item_id in ids if self.items.get(item_id).status is ItemStatus.PLANNED]
            # Review and failed files are settled now; planned ones once they are published.
            self._advance(len(ids) - len(waiting) - (len(ready) if on_planned is not None else 0))
            if on_planned is not None and ready:
                on_planned(ready)
            return waiting

        waiting: List[Tuple[int, SourceEntry]] = []
        for folder, entries in folders.items():
            if self.should_stop():
                break
            self._report(current=folder if folder is not None else entries[0].path.name)
            todo: List[Tuple[int, SourceEntry]] = []
            for entry in entries:
                try:
                    source_fingerprint = fingerprint(entry.path)
                except OSError:
                    self._advance()
                    continue  # vanished or unreadable between scan and fingerprint; next scan sees it
                existing = self.items.find_by_fingerprint(library_id, source_fingerprint)
                if existing is not None and existing.id not in seen:
                    existing = self._follow(library, existing, entry)
                # Same bytes seen earlier in this very scan (a copy in another folder), or already settled.
                if existing is not None and (existing.id in seen or existing.status not in _RESUMABLE):
                    known += 1
                    self._advance()
                    continue
                # An earlier scan interrupted before planning is simply redone.
                item = existing or self.items.create(library_id, entry.path, source_fingerprint, run_id=run_id,
                                                     group_key=review_group(library, entry.path, entry.root),
                                                     source_root=entry.root)
                todo.append((item.id, entry))
                seen.add(item.id)
            if not todo:
                continue
            everything.extend(item_id for item_id, _ in todo)
            waiting.extend(settle(todo))
        if waiting and self._ai_failures < _AI_FAILURE_LIMIT and not self.should_stop():
            # One more try for what the AI could not answer: it is often only busy for a while.
            for _, entry in waiting:
                del self._readings[str(entry.path)]
            self._report(current=None)
            waiting = settle(waiting)
        self._advance(len(waiting))  # these wait for the next scan
        self._report(current=None)
        counts = self._counts(everything)
        counts["known"] = known
        self.runs.finish(run_id, counts)
        return run_id

    def retry(self, item_ids: Sequence[int]) -> Dict[str, int]:
        """Failed builds go back to READY; parked, stuck, scan-failed and duplicate items are redone."""
        counts = {"ready": 0, "replanned": 0, "skipped": 0}
        redo: List[int] = []
        for item_id in item_ids:
            item = self.items.get(item_id)
            if item.status is ItemStatus.FAILED and item.plan.get("metadata"):
                self.items.transition(item.id, ItemStatus.READY, event="retry")
                counts["ready"] += 1
            elif item.status in _RESUMABLE or item.status in (ItemStatus.FAILED, ItemStatus.DUPLICATE):
                redo.append(item.id)
                counts["replanned"] += 1
            else:
                counts["skipped"] += 1
        self.replan(redo)
        return counts

    def reidentify(self, item_ids: Sequence[int]) -> Dict[str, int]:
        """Ask the AI again about items waiting for review; what it is still unsure of goes back to review.
        Other items are skipped."""
        waiting = []
        for item_id in item_ids:
            try:
                if self.items.get(item_id).status is ItemStatus.NEEDS_REVIEW:
                    waiting.append(item_id)
            except KeyError:  # removed meanwhile: counted as skipped
                pass
        if waiting and self.services.ai is None:
            raise AiNotConfigured()
        self.replan(waiting, include_review=True)
        for item_id in waiting:
            # AI or Bangumi unreachable leaves the item parsed (a later scan resumes it); here it was in review.
            if self.items.get(item_id).status is ItemStatus.PARSED:
                self._review(item_id, ReviewReason.METADATA, "review",
                             {"note": "AI 或 Bangumi 暂时无法访问，稍后再重新识别"})
        counts = self._counts(waiting)
        counts["skipped"] = len(item_ids) - len(waiting)
        return counts

    def replan(self, item_ids: Sequence[int], *, include_review: bool = False) -> None:
        """Redo recognition, matching and planning (e.g. after Bangumi was unreachable)."""
        self._reset()
        libraries: Dict[int, Library] = {}
        todo: Dict[int, List[Tuple[int, SourceEntry]]] = {}
        for item_id in item_ids:
            item = self.items.get(item_id)
            allowed = item.status in _RESUMABLE or item.status in (ItemStatus.FAILED, ItemStatus.DUPLICATE) or (
                include_review and item.status is ItemStatus.NEEDS_REVIEW)
            if not allowed:
                continue
            if item.library_id not in libraries:
                library = libraries[item.library_id] = self.libraries.get(item.library_id)
                require_directories(library)
            located = locate_source(item.source_path)
            if located is None:
                self._source_gone(item, "source_missing")
                continue
            if located != item.source_path:
                item = self.items.update(item.id, event="source_moved", detail={"to": str(located)},
                                         source_path=located)
            try:
                entry = entry_for(libraries[item.library_id], item.source_path, item.source_root)
            except Exception as error:  # e.g. scanned under a source dir the library no longer has
                self._fail(item.id, error)
                continue
            todo.setdefault(item.library_id, []).append((item.id, entry))
        for library_id, entries in todo.items():
            library = libraries[library_id]
            adapter = adapter_for(library)
            self._prepare(library, adapter, entries)
            matched: List[PlanInput] = []
            try:
                for item_id, entry in entries:
                    if self.should_stop():
                        break
                    planned = self._process(item_id, library, adapter, entry)
                    if planned is not None:
                        matched.append(planned)
            finally:
                # Items already matched must be planned even when the run stops part-way (e.g. the share went away).
                self._plan(library, matched)

    # ---- review, reorganize, cancel -----------------------------------------------------------

    def _validate(self, **choices) -> None:
        validate_choices(sources=self.services.sources.names, **choices)

    def confirm(self, item_ids: Sequence[int], *, title: Optional[str] = None, edition: Optional[str] = None,
                subject: Optional[SubjectRef] = None, volumes: Mapping[int, str] = {},
                skip_metadata: bool = False) -> Dict[str, int]:
        """Settle reviewed items: the choices are kept on each item (so it is not asked again), then planned.

        ``skip_metadata`` organizes them under the title without looking for a metadata subject."""
        self._validate(title=title, edition=edition, subject=subject, volumes=volumes)
        counts = {"replanned": 0, "skipped": 0}
        items = []
        for item_id in item_ids:
            item = self.items.get(item_id)
            if item.status not in _CONFIRMABLE:
                counts["skipped"] += 1
                continue
            if item.id in volumes:  # before anything changes: a novel takes fewer forms than a manga
                parse_volume_for(self.libraries.get(item.library_id).kind, volumes[item.id])
            items.append(item)
        if title is None and subject is not None and any(item.review_reason is ReviewReason.NAMING for item in items):
            # Picking a subject for a folder whose name could not be read: the subject names the series.
            title = self.services.sources.get(subject.source).get(subject.id).display_title
            self._validate(title=title, edition=edition, subject=subject, volumes={})
        chosen = {key: value for key, value in (("title", title), ("edition", edition)) if value not in (None, "")}
        if subject is not None and not skip_metadata:
            chosen["subject"] = subject.to_json()
        redo = []
        if skip_metadata:
            chosen["no_metadata"] = True
        for item in items:
            overrides = dict(item.overrides or {}, **chosen)
            if skip_metadata:
                overrides.pop("subject", None)
                overrides.pop("bgm", None)
            elif "subject" in chosen:
                overrides.pop("bgm", None)  # how a choice was kept before there were other sources
                overrides.pop("no_metadata", None)  # a subject picked now replaces an earlier skip
                overrides.pop("metadata", None)  # and what was filled in by hand
            if item.id in volumes:
                overrides["volume"] = str(volumes[item.id]).strip()
            if overrides != (item.overrides or {}):
                self.items.set_overrides(item.id, overrides)
            if item.status is not ItemStatus.PARSED:
                self.items.transition(item.id, ItemStatus.PARSED, event="confirmed_in_review",
                                      detail={"title": title, "edition": edition, "subject": _ref_json(subject),
                                              "volume": volumes.get(item.id)})
            redo.append(item.id)
        self.replan(redo)
        counts["replanned"] = len(redo)
        return counts

    def reorganize(self, item_ids: Sequence[int], *, title: Optional[str] = None, edition: Optional[str] = None,
                   subject: Optional[SubjectRef] = None, volumes: Mapping[int, str] = {}) -> Dict[str, int]:
        """Redo published items: the old output is deleted first, then the item is recognized and planned again."""
        self._validate(title=title, edition=edition, subject=subject, volumes=volumes)
        counts = {"deleted": 0, "replanned": 0, "skipped": 0}
        items = [self.items.get(item_id) for item_id in item_ids]
        for library_id in {item.library_id for item in items}:
            require_directories(self.libraries.get(library_id))  # before anything is deleted
        published = []
        for item in items:
            if item.status is not ItemStatus.PUBLISHED:
                counts["skipped"] += 1
                continue
            library = self.libraries.get(item.library_id)
            source = Path(item.source_path)
            try:
                rebuildable = os.path.lexists(source) and fingerprint(source) == item.fingerprint
            except OSError:
                rebuildable = False
            if not rebuildable:
                # Archived, deleted or edited since publishing: keep the published file, it may be the only copy.
                self.items.add_event(item.id, "reorganize_refused", {"note": "来源文件已不在或已变"})
                counts["skipped"] += 1
                continue
            target = library.library_dir / item.target_path if item.target_path else None
            if target is not None and os.path.lexists(target):
                remove_tree(target)
                counts["deleted"] += 1
            self.items.add_event(item.id, "target_deleted",
                                 {"target": item.target_path.as_posix() if item.target_path else None})
            self.items.transition(item.id, ItemStatus.PARSED, event="reorganize",
                                  detail={"title": title, "edition": edition, "subject": _ref_json(subject)})
            published.append(item.id)
        result = self.confirm(published, title=title, edition=edition, subject=subject, volumes=volumes)
        counts["replanned"] = result["replanned"]
        return counts

    def edit_metadata(self, item_ids: Sequence[int], *, subject: Optional[SubjectRef] = None,
                      manual: Optional[ManualMetadata] = None) -> Dict[str, object]:
        """Rewrite the metadata inside organized files, from a source's subject or from what a person typed.

        Only the metadata changes: pages are copied as they are, so no source file is needed.
        ``ids`` and ``series`` in the result name what changed, for telling the media servers.
        """
        if (subject is None) == (manual is None):
            raise ValueError("要选一个条目或手填元数据")
        if subject is not None:
            self._validate(subject=subject)
            subject = self.services.sources.get(subject.source).get(subject.id)
        counts: Dict[str, object] = {"edited": 0, "skipped": 0, "failed": 0, "ids": [], "series": []}
        for item_id in item_ids:
            item = self.items.get(item_id)
            if item.status is not ItemStatus.PUBLISHED or not item.target_path or "metadata" not in (item.plan or {}):
                counts["skipped"] += 1
                continue
            library = self.libraries.get(item.library_id)
            before = metadata_from_json(library.kind, item.plan["metadata"])
            after = apply_subject(before, subject) if subject is not None else apply_manual(before, manual)
            path = library.library_dir / item.target_path
            try:
                if not path.is_file():
                    raise FileNotFoundError(2, "文件不见了", str(path))
                (rewrite_epub if library.kind == "novel" else rewrite_cbz)(path, after)
            except Exception as error:
                self.items.add_event(item.id, "metadata_edit_failed",
                                     {"error": failure.describe(error), "raw": failure.raw(error)})
                counts["failed"] += 1
                continue
            overrides = dict(item.overrides or {})
            if subject is not None:
                overrides.pop("metadata", None)
                overrides.pop("no_metadata", None)
                overrides.pop("bgm", None)
                overrides["subject"] = subject.ref.to_json()
            else:
                overrides["metadata"] = manual.to_json()
            self.items.set_overrides(item.id, overrides)
            plan = dict(item.plan, metadata=metadata_to_json(after))
            fields = {"plan": plan}
            if subject is not None:
                fields["subject_id"] = subject.subject_id
                fields["subject_source"] = subject.source
            detail = {"subject": subject.ref.to_json()} if subject is not None else {"fields": manual.to_json()}
            self.items.update(item.id, event="metadata_edited", detail=detail, **fields)
            counts["edited"] += 1
            counts["ids"].append(item.id)
            series = (item.library_id, item.plan.get("series"))
            if series[1] and series not in counts["series"]:
                counts["series"].append(series)
        return counts

    def refresh_metadata(self, item_ids: Sequence[int]) -> Dict[str, object]:
        """Write what Bangumi says today into organized files; a file with nothing new is left alone.

        What a person filled in by hand stays, and so do files without a subject. ``ids`` and ``series`` in the
        result name what changed, for telling the media servers.
        """
        counts: Dict[str, object] = {"refreshed": 0, "unchanged": 0, "skipped": 0, "failed": 0, "ids": [], "series": []}
        subjects: Dict[SubjectRef, object] = {}
        for item_id in item_ids:
            if self.should_stop():
                break
            self._advance()
            item = self.items.get(item_id)
            overrides = item.overrides or {}
            ref = item.subject_ref
            if (item.status is not ItemStatus.PUBLISHED or not item.target_path or ref is None
                    or "metadata" not in (item.plan or {}) or overrides.get("metadata")):
                counts["skipped"] += 1
                continue
            try:
                if ref not in subjects:
                    # Its own source, switched on or not: what was organized from it stays refreshable.
                    subjects[ref] = self.services.sources.get(ref.source).get(ref.id, fresh=True)
                library = self.libraries.get(item.library_id)
                before = metadata_from_json(library.kind, item.plan["metadata"])
                after = apply_subject(before, subjects[ref])
                if library.kind == "novel" and not before.description:
                    after = replace(after, description="")  # only a series' first volume carries the summary
                new = metadata_to_json(after)
                if new == item.plan["metadata"]:
                    counts["unchanged"] += 1
                    continue
                path = library.library_dir / item.target_path
                if not path.is_file():
                    raise FileNotFoundError(2, "文件不见了", str(path))
                (rewrite_epub if library.kind == "novel" else rewrite_cbz)(path, after)
            except Exception as error:  # one file, or Bangumi being away, must not stop the rest
                self.items.add_event(item.id, "metadata_refresh_failed",
                                     {"error": failure.describe(error), "raw": failure.raw(error)})
                counts["failed"] += 1
                continue
            self.items.update(item.id, event="metadata_refreshed", detail={"subject": ref.to_json()},
                              plan=dict(item.plan, metadata=new))
            counts["refreshed"] += 1
            counts["ids"].append(item.id)
            series = (item.library_id, item.plan.get("series"))
            if series[1] and series not in counts["series"]:
                counts["series"].append(series)
        return counts

    def set_cover(self, item_id: int, page: str, left: Optional[float] = None,
                  right: Optional[float] = None) -> Dict[str, object]:
        """Choose one file's cover; it is kept on the item, so reorganizing the file keeps it too."""
        item = self.items.get(item_id)
        if item.status is not ItemStatus.PUBLISHED or not item.target_path:
            raise ValueError("只有已整理的文件才能设置封面")
        library = self.libraries.get(item.library_id)
        if library.kind != "manga":
            raise ValueError("只有漫画才能换封面")
        path = library.library_dir / item.target_path
        covers.set_cover(path, page, left, right)
        self._remember_cover(item, path, page, left, right)
        series = (item.plan or {}).get("series")
        return {"ids": [item.id], "series": [(item.library_id, series)] if series else []}

    def _remember_cover(self, item: Item, path: Path, page: str, left, right) -> None:
        overrides = dict(item.overrides or {})
        if not covers.cover_options(path).added:
            overrides.pop("cover", None)  # back to the file's own first page
        else:
            overrides["cover"] = {"page": page, "left": left, "right": right}
        self.items.set_overrides(item.id, overrides)
        self.items.add_event(item.id, "cover_set", {"page": page, "cropped": left is not None or right is not None})

    def crop_jackets(self, item_ids: Sequence[int]) -> Dict[str, object]:
        """Crop every volume whose first page is a whole jacket and that has no cover of its own yet."""
        counts: Dict[str, object] = {"cropped": 0, "skipped": 0, "failed": 0, "ids": [], "series": []}
        for item_id in item_ids:
            if self.should_stop():
                break
            self._advance()
            item = self.items.get(item_id)
            library = self.libraries.get(item.library_id)
            if item.status is not ItemStatus.PUBLISHED or not item.target_path or library.kind != "manga":
                counts["skipped"] += 1
                continue
            path = library.library_dir / item.target_path
            try:
                options = covers.cover_options(path)
                if options.added or options.jacket is None:
                    counts["skipped"] += 1
                    continue
                jacket = options.jacket
                covers.set_cover(path, jacket.page, jacket.left, jacket.right)
                self._remember_cover(item, path, jacket.page, jacket.left, jacket.right)
            except Exception as error:  # a broken file must not stop the rest
                self.items.add_event(item.id, "cover_failed", {"error": failure.describe(error), "raw": failure.raw(error)})
                counts["failed"] += 1
                continue
            counts["cropped"] += 1
            counts["ids"].append(item.id)
            series = (item.library_id, (item.plan or {}).get("series"))
            if series[1] and series not in counts["series"]:
                counts["series"].append(series)
        return counts

    def cancel(self, item_ids: Sequence[int]) -> Dict[str, int]:
        counts = {"cancelled": 0, "skipped": 0}
        for item_id in item_ids:
            item = self.items.get(item_id)
            if item.status in (ItemStatus.PLANNED, ItemStatus.READY, ItemStatus.NEEDS_REVIEW):
                self.items.transition(item.id, ItemStatus.CANCELLED, event="cancelled")
                counts["cancelled"] += 1
            else:
                counts["skipped"] += 1
        return counts

    # ---- sources that moved or went away ------------------------------------------------------

    def _follow(self, library: Library, item: Item, entry: SourceEntry) -> Item:
        """A scan found the item's bytes at ``entry.path``: renamed (or respelled) sources keep their item."""
        path = entry.path
        if item.source_path != path and not os.path.lexists(item.source_path):
            item = self.items.update(item.id, event="source_moved", detail={"to": str(path)}, source_path=path,
                                     source_root=entry.root, group_key=review_group(library, path, entry.root))
        if item.status is ItemStatus.CANCELLED and item.error in _SOURCE_GONE:
            item = self.items.transition(item.id, ItemStatus.PARSED, event="source_back", error=None)
        return item

    def _source_gone(self, item: Item, event: str) -> None:
        """No review for a source that is gone or changed: the item is set aside until a scan finds it again."""
        if ItemStatus.CANCELLED in TRANSITIONS[item.status]:
            self.items.transition(item.id, ItemStatus.CANCELLED, event=event, error=event)
        else:
            self.items.add_event(item.id, event)

    # ---- recognition ------------------------------------------------------------------------

    def _reset(self) -> None:
        self._readings = {}
        self._ai_memo = {}
        self._settled = {}
        self._ai_failures = 0
        self._folder_sources = {}
        self._folder_sources_loaded = set()

    def _prepare(self, library: Library, adapter: KindAdapter, todo: Sequence[Tuple[int, SourceEntry]]) -> None:
        """Ask the AI about every source that needs it, a batch of one folder's names per call."""
        # By root as well: two dropped folders of the same name hold the same relative names.
        groups: Dict[Tuple[Optional[Path], Optional[str]], List[Tuple[int, SourceEntry]]] = {}
        for item_id, entry in todo:
            if str(entry.path) in self._readings or not _needs_ai(self.items.get(item_id)):
                continue
            groups.setdefault((entry.root, entry.series_folder), []).append((item_id, entry))
        if not groups:
            return
        ai = self.services.ai
        if ai is None:
            raise AiNotConfigured()
        threshold = _effective_threshold(self.services.config.ai_threshold)
        known_series, known_editions = _library_names(library.library_dir)
        for (_, folder), members in groups.items():
            by_name = {_name_in_folder(library, entry): (item_id, entry) for item_id, entry in members}
            facts = {}
            for name, (_, entry) in by_name.items():
                found = adapter.facts(entry)
                if found:
                    facts[name] = found
            for batch in batches(list(by_name)):
                if self._ai_failures >= _AI_FAILURE_LIMIT:
                    readings = {name: Reading(problem="AI 连续多次连不上，这次不再问", retry=True) for name in batch}
                else:
                    readings = read_batch(ai, kind=library.kind, folder=folder, names=batch, facts=facts,
                                          settled=self._settled.get(folder, ()), library_series=known_series,
                                          library_editions=known_editions, item_id=by_name[batch[0]][0])
                    unreachable = any(reading.retry for reading in readings.values())
                    self._ai_failures = self._ai_failures + 1 if unreachable else 0
                for name in batch:
                    self._readings[str(by_name[name][1].path)] = readings[name]
                if folder is not None:
                    # Later batches of the folder keep the names of every work a confident answer named so far.
                    settled = self._settled.setdefault(folder, [])
                    for reading in readings.values():
                        series = reading.series
                        if series is not None and series.confidence >= threshold \
                                and all(known.title != series.title for known in settled):
                            settled.append(series)

    def _process(self, item_id: int, library: Library, adapter: KindAdapter,
                 entry: SourceEntry) -> Optional[PlanInput]:
        try:
            return self._recognize_and_match(item_id, library, adapter, entry)
        except Exception as error:  # one broken source must not stop the scan
            self._fail(item_id, error)
            return None

    def _recognize_and_match(self, item_id: int, library: Library, adapter: KindAdapter,
                             entry: SourceEntry) -> Optional[PlanInput]:
        overrides = self.items.get(item_id).overrides or {}
        reading = self._readings.get(str(entry.path))
        series = reading.series if reading is not None else None
        file = reading.file if reading is not None else None
        threshold = _effective_threshold(self.services.config.ai_threshold)
        chosen = SubjectRef.from_overrides(overrides)
        title = overrides.get("title") or (series.title if series is not None else "")
        edition = overrides["edition"] if "edition" in overrides else (series.edition if series else None)
        if library.kind == "novel":
            edition = None  # novels have no editions
        search_titles = series.search_titles if series is not None and not overrides.get("title") else ()
        if "volume" in overrides:
            volume = parse_volume_for(library.kind, overrides["volume"])
        else:
            volume = adapter.volume_from_ai(file) if file is not None else None
        parse = ParseResult(title, edition, volume, adapter.facts(entry), search_titles)
        self._mark_parsed(item_id, parse, reading)
        # A guess is no reason to put files together: the AI calls every file it cannot place the same thing.
        trusted = overrides.get("title") or (series is not None and series.confidence >= threshold)
        if title and trusted and _is_loose_drop(entry):
            self.items.update(item_id, event="grouped_by_title", group_key=unicodedata.normalize("NFC", title))
        if reading is not None and reading.retry:
            self.items.add_event(item_id, "ai_retry", {"error": reading.problem})
            return None
        if not (overrides.get("title") or chosen):
            if series is None:
                self._review(item_id, ReviewReason.NAMING, "review",
                             {"note": reading.problem if reading is not None else "AI 没有识别这个文件"})
                return None
            if series.confidence < threshold:
                self.items.add_event(item_id, "ai_suggestion", _reading_json(reading))
                self._review(item_id, ReviewReason.NAMING, "review", {"note": "AI 对书名没有把握"})
                return None
        if "volume" not in overrides and (file is None or file.confidence < threshold or volume is None):
            if reading is not None and reading.series is not None:
                self.items.add_event(item_id, "ai_suggestion", _reading_json(reading))
            note = "AI 对卷号没有把握" if file is not None else (reading.problem if reading else "没有卷号")
            self._review(item_id, ReviewReason.VOLUME, "volume", {"note": note})
            return None
        recognition = Recognition(parse)
        if overrides.get("no_metadata"):
            # Chosen in review: organize under the title, no Bangumi lookup.
            self.items.transition(item_id, ItemStatus.MATCHED, event="no_metadata",
                                  detail={"title": parse.title_hint, "chosen": True}, subject_id=None,
                                  subject_source=None)
            subject = Subject.unlisted(parse.title_hint)
        elif series is not None and series.base_title and not overrides.get("title") and not chosen:
            organized = self._match_sub_series(item_id, library, adapter, parse, reading, entry, "volume" in overrides)
            if organized is None:
                return None
            recognition, subject = organized
        else:
            subject = self._match(item_id, library, recognition, entry, chosen)
        if subject is None:
            return None
        suffix = adapter.output_suffix(entry) if hasattr(adapter, "output_suffix") else ".epub"
        return PlanInput(item_id, entry, recognition, subject, suffix)

    def _match_sub_series(self, item_id: int, library: Library, adapter: KindAdapter, parse: ParseResult,
                          reading: Reading, entry: SourceEntry,
                          volume_chosen: bool) -> Optional[Tuple[Recognition, Subject]]:
        """With an entry of its own a sub-series is a series; without one its files join the original."""
        config = self.services.config
        base_title = reading.series.base_title
        own = None
        for source in self._sources_for(library, entry):  # the next source only when this one surely has none
            own = find_own_entry(
                source, kind=library.kind, title=parse.title_hint, base_title=base_title,
                search_titles=parse.search_titles,
                context=SourceContext(source_folder=entry.series_folder, names=(entry.path.name,),
                                      title_hint=parse.title_hint),
                ai=self.services.ai, threshold=config.ai_threshold, item_id=item_id, memo=self._ai_memo,
            )
            if not own.none_found:
                break
        if own.retry:
            self.items.add_event(item_id, "metadata_retry", {"error": own.error})
            return None
        if own.config_error:
            self.items.add_event(item_id, "metadata_config_error", {"error": own.error})
            return None
        if own.subject is not None:
            recognition = Recognition(parse)
            subject = self._match(item_id, library, recognition, entry, own.subject.ref)
            return (recognition, subject) if subject is not None else None
        if not own.none_found:
            self._review(item_id, ReviewReason.METADATA, "review", {"note": own.error or own.note})
            return None
        part = _part_name(parse.title_hint, base_title)
        volume = parse.volume if volume_chosen else adapter.volume_from_ai(_as_special(reading.file, part))
        merged = replace(parse, title_hint=base_title, volume=volume, search_titles=())
        recognition = Recognition(merged)
        subject = self._match(item_id, library, recognition, entry, None)
        if subject is None:
            return None
        self.items.update(item_id, event="merged_into_original", detail={"original": base_title, "part": part},
                          parsed=_parsed_json(merged, reading))
        return recognition, subject

    def _mark_parsed(self, item_id: int, parse: ParseResult, reading: Optional[Reading]) -> None:
        status = self.items.get(item_id).status
        parsed = _parsed_json(parse, reading)
        if status is ItemStatus.PARSED:  # replan: refresh, status unchanged
            self.items.update(item_id, event="reparsed", parsed=parsed)
            return
        event = "parsed" if status is ItemStatus.DISCOVERED else "reparsed"
        self.items.transition(item_id, ItemStatus.PARSED, event=event, parsed=parsed)

    def _sources_for(self, library: Library, entry: SourceEntry) -> Sequence:
        """The enabled sources in order; a folder already organized from one source stays with it."""
        sources = self.services.sources
        if entry.series_folder is None:
            return sources.enabled
        if (library.id, entry.root) not in self._folder_sources_loaded:
            self._folder_sources_loaded.add((library.id, entry.root))
            root = entry.root if entry.root is not None else library.source_dir
            for folder, name in self.items.subject_sources_by_folder(library.id, root).items():
                self._folder_sources.setdefault((library.id, entry.root, folder), name)
        name = self._folder_sources.get((library.id, entry.root, entry.series_folder))
        if name is not None and name in sources.names:
            return (sources.get(name),)
        return sources.enabled

    def _remember_source(self, library: Library, entry: SourceEntry, subject: Subject) -> None:
        if entry.series_folder is not None and subject.source in self.services.sources.names:
            self._folder_sources.setdefault((library.id, entry.root, entry.series_folder), subject.source)

    def _match(self, item_id: int, library: Library, recognition: Recognition, entry: SourceEntry,
               chosen: Optional[SubjectRef]) -> Optional[Subject]:
        config = self.services.config
        parse = recognition.parse
        options = dict(
            kind=library.kind, title_hint=parse.title_hint, search_titles=parse.search_titles,
            context=SourceContext(source_folder=entry.series_folder, names=(entry.path.name,),
                                  title_hint=parse.title_hint),
            ai=self.services.ai, threshold=config.ai_threshold, item_id=item_id, memo=self._ai_memo,
        )
        if chosen is not None:
            try:
                source = self.services.sources.get(chosen.source)
            except KeyError:
                self._review(item_id, ReviewReason.METADATA, "review",
                             {"note": "数据源 {0} 已不可用".format(chosen.source)})
                return None
            result = match_subject(source, forced_id=chosen.id, **options)
        else:
            result = match_across(self._sources_for(library, entry), forced_id=None, **options)
        if result.retry:
            self.items.add_event(item_id, "metadata_retry", {"error": result.error})
            return None
        if result.config_error:
            self.items.add_event(item_id, "metadata_config_error", {"error": result.error})
            return None
        candidates = [scored.subject.ref.to_json() for scored in result.candidates]
        if result.method in ("rule", "auto", "ai"):
            self._remember_source(library, entry, result.subject)
            if result.method == "ai":
                self.items.add_event(item_id, "ai_adopted", _suggestion_json(result.suggestion))
                if result.suggestion.call_id is not None:
                    self.ai_calls.mark_adopted(result.suggestion.call_id)
            self.items.transition(item_id, ItemStatus.MATCHED, event="matched",
                                  detail={"method": result.method, "subject_id": result.subject.subject_id,
                                          "source": result.subject.source, "title": result.subject.display_title},
                                  subject_id=result.subject.subject_id, subject_source=result.subject.source)
            return result.subject
        if result.suggestion is not None:
            self.items.add_event(item_id, "ai_suggestion", _suggestion_json(result.suggestion))
        # No subject settled: the user decides in review (pick one, or organize without metadata). Offer what
        # the AI looked at, its own guess first.
        suggestion = result.suggestion
        offered = [subject.ref.to_json() for subject in result.offered]
        picked = [entry for entry in offered if suggestion is not None and entry["id"] == suggestion.subject_id]
        offered = picked + [entry for entry in offered if entry not in picked]
        merged: List[dict] = []
        for entry in offered + candidates:
            if entry not in merged:
                merged.append(entry)
        candidates = merged
        label = result.label or "数据源"
        if result.error:
            note = result.error
        elif not candidates:
            note = "{0} 上没有搜到".format(label)
        elif result.ai_says_none:
            note = "{0} 候选里没有这部作品".format(label)
        else:
            note = "AI 对 {0} 条目没有把握".format(label)
        self._review(item_id, ReviewReason.METADATA, "review", {"note": note, "candidates": candidates})
        return None

    # ---- planning ---------------------------------------------------------------------------

    def _plan(self, library: Library, inputs: Sequence[PlanInput]) -> None:
        if not inputs:
            return
        template = library.naming_template or DEFAULT_TEMPLATE
        try:
            decisions = plan_batch(library.kind, library.library_dir, template, inputs,
                                   include_edition=library.include_edition,
                                   owner_of=lambda target: self.items.published_owner(library.id, target),
                                   overwrite=library.overwrite_policy, rename=library.rename_files,
                                   published=self.items.published_volumes(library.id),
                                   source_time=lambda target: self._source_time(library, target))
        except Exception as error:
            for item in inputs:
                self._fail(item.item_id, error)
            return
        for decision in decisions:
            try:
                self._apply_decision(decision)
            except Exception as error:  # one item's bookkeeping must not abort the batch
                self._fail(decision.item_id, error)

    def _source_time(self, library: Library, target: Path) -> Optional[float]:
        owner = self.items.published_owner(library.id, target)
        return self.items.get(owner).plan.get("source_mtime") if owner is not None else None

    def _apply_decision(self, decision) -> None:
        detail = {"note": decision.note, "series": decision.series_name,
                  "target": decision.target.as_posix() if decision.target else None}
        if decision.status == "planned":
            self.items.transition(
                decision.item_id, ItemStatus.PLANNED, event="planned", detail=detail,
                target_path=decision.target,
                plan={"series": decision.series_name, "volume": decision.volume_key,
                      "metadata": decision.metadata, "fields": decision.fields,
                      "source_mtime": decision.source_mtime,
                      **({"replaces": decision.replaces.as_posix()} if decision.replaces is not None else {})},
            )
        elif decision.status == "claimed":
            # Already in the library: record it as published, but leave the source alone.
            self.items.transition(
                decision.item_id, ItemStatus.PUBLISHED, event="claimed", detail=detail,
                target_path=decision.target,
                plan={"series": decision.series_name, "volume": decision.volume_key,
                      "metadata": decision.metadata, "fields": decision.fields},
            )
        elif decision.status == "duplicate":
            self.items.transition(decision.item_id, ItemStatus.DUPLICATE, event="duplicate", detail=detail,
                                  target_path=decision.target)
        else:
            self.items.transition(decision.item_id, ItemStatus.NEEDS_REVIEW, event="review", detail=detail,
                                  review_reason=decision.review_reason)

    # ---- execute ----------------------------------------------------------------------------

    def execute(self, item_ids: Sequence[int]) -> Dict[str, int]:
        """Build, publish and dispose PLANNED (or recovered READY) items, one at a time."""
        counts = {"published": 0, "failed": 0, "review": 0, "skipped": 0}
        items = [self.items.get(item_id) for item_id in item_ids]
        for library_id in {item.library_id for item in items}:
            require_directories(self.libraries.get(library_id))  # never publish onto an unmounted share
        for item_id in item_ids:
            if self.should_stop():
                break
            item = self.items.get(item_id)
            if item.status not in (ItemStatus.PLANNED, ItemStatus.READY):
                counts["skipped"] += 1
            else:
                counts[self._execute_one(item)] += 1
            self._advance()
        return counts

    def _execute_one(self, item) -> str:
        library = self.libraries.get(item.library_id)
        adapter = adapter_for(library)
        source = locate_source(item.source_path)
        if source is None:
            self._source_gone(item, "source_missing")
            return "skipped"
        if source != item.source_path:
            item = self.items.update(item.id, event="source_moved", detail={"to": str(source)}, source_path=source)
        try:
            unchanged = fingerprint(source) == item.fingerprint
        except OSError:
            unchanged = False
        if not unchanged:
            # Still downloading or replaced: the next scan reads the new bytes as a new item.
            self._source_gone(item, "source_changed")
            return "skipped"
        try:
            entry = entry_for(library, source, item.source_root)
        except ValueError:
            self.items.add_event(item.id, "source_changed", {"note": "来源不在库的来源目录里"})
            self._review(item.id, ReviewReason.NAMING, "review", {"note": "来源不在库的来源目录里"})
            return "review"
        if item.status is ItemStatus.PLANNED:
            self.items.transition(item.id, ItemStatus.READY, event="confirmed")
        self.items.transition(item.id, ItemStatus.BUILDING, event="building")
        final = library.library_dir / item.target_path
        replaces = (item.plan or {}).get("replaces")
        if replaces is None and os.path.lexists(final):  # found now, not after minutes of repacking
            self.items.transition(item.id, ItemStatus.NEEDS_REVIEW, event="review",
                                  detail={"note": "目标位置已经有文件了"}, review_reason=ReviewReason.CONFLICT)
            return "review"
        problem = failure.preflight(library.library_dir, source)
        if problem is not None:
            self._fail(item.id, message=problem)
            return "failed"
        publisher = Publisher(JournalStore(self.services.db))
        try:
            metadata = metadata_from_json(library.kind, item.plan["metadata"])
            if (item.overrides or {}).get("metadata"):  # filled in by hand earlier: kept over a rebuild
                metadata = apply_manual(metadata, ManualMetadata.from_json(item.overrides["metadata"]))
            if library.kind == "novel":
                metadata = NovelPlan(source, metadata)
            overwrite = replaces is not None
            staged = publisher.start(item.id, library.library_dir, final, overwrite=overwrite)
            adapter.build(entry, metadata, staged)
            result = publisher.commit(item.id, verify=lambda path: adapter.verify(path, metadata), overwrite=overwrite)
        except TargetExists:
            publisher.abort(item.id)
            self.items.transition(item.id, ItemStatus.NEEDS_REVIEW, event="review",
                                  detail={"note": "入库前目标位置出现了文件"},
                                  review_reason=ReviewReason.CONFLICT)
            return "review"
        except Exception as error:
            publisher.abort(item.id)
            self._fail(item.id, error)
            return "failed"
        detail = {"sha256": result.sha256, "size": result.size, "method": result.method}
        if result.method == "fallback":
            detail["note"] = "文件系统不支持硬链接，改用先检查再改名的方式入库"
        self.items.transition(item.id, ItemStatus.PUBLISHED, event="published", detail=detail)
        if replaces is not None:
            self._retire_replaced(library, item, replaces)
        self._restore_cover(library, self.items.get(item.id), final)
        self._dispose(library, self.items.get(item.id))
        return "published"

    def _restore_cover(self, library: Library, item: Item, path: Path) -> None:
        """A rebuilt file gets the cover a person chose for it; failing that it still is in the library."""
        cover = (item.overrides or {}).get("cover")
        if not cover or library.kind != "manga":
            return
        try:
            covers.set_cover(path, cover["page"], cover.get("left"), cover.get("right"))
        except Exception as error:
            self.items.add_event(item.id, "cover_failed", {"error": failure.describe(error), "raw": failure.raw(error)})

    def _retire_replaced(self, library: Library, item: Item, replaces: str) -> None:
        """The new file is in place: what it replaced goes, and so do the records of that file."""
        old = Path(replaces)
        if old != item.target_path:
            try:
                (library.library_dir / old).unlink()
            except FileNotFoundError:
                pass
            except OSError as error:
                self.items.add_event(item.id, "replaced_file_kept", {"file": replaces, "error": str(error)})
        for owner in self.items.published_at(library.id, old):
            if owner != item.id:
                self.items.transition(owner, ItemStatus.DUPLICATE, event="replaced", detail={"by": item.id})
        plan = {key: value for key, value in item.plan.items() if key != "replaces"}
        self.items.update(item.id, event="target_replaced", detail={"file": replaces}, plan=plan)

    def _dispose(self, library: Library, item) -> None:
        policy = library.source_policy
        if item.source_root is not None:
            policy = "keep"  # dropped in from the user's own folders: only the user decides what happens to it
        elif library.source_managed and policy == "keep":
            policy = "delete"  # an upload waiting under the data dir is not kept once organized
        context = DisposalContext(policy=policy, source_root=library.source_dir,
                                  archive_dir=library.archive_dir)
        try:
            outcome = dispose_source(context, Path(item.source_path), item.fingerprint)
        except Exception as error:  # the output is published; a stuck source is reported, not fatal
            self.items.add_event(item.id, "source_disposal_failed", {"error": str(error)})
            return
        self.items.add_event(item.id, "source_disposed", {
            "outcome": outcome.outcome,
            "destination": outcome.destination.as_posix() if outcome.destination else None,
        })

    # ---- recovery ---------------------------------------------------------------------------

    def recover(self) -> None:
        """Run at startup: settle interrupted publications and clean staging."""
        journal = JournalStore(self.services.db)
        publisher = Publisher(journal)
        try:
            outcomes = publisher.recover()
        except OSError:
            # e.g. a stale SMB mount: leave BUILDING items alone and try again next start.
            outcomes = None
        for outcome in outcomes or ():
            item = self.items.get(outcome.item_id)
            if item.status is not ItemStatus.BUILDING:
                continue
            if outcome.outcome == "published":
                self.items.transition(item.id, ItemStatus.PUBLISHED, event="published",
                                      detail={"note": "重启后已恢复"})
                self._dispose(self.libraries.get(item.library_id), self.items.get(item.id))
            elif outcome.outcome == "reset":
                self.items.transition(item.id, ItemStatus.READY, event="recovered",
                                      detail={"note": "中断的整理已丢弃"})
            else:
                self.items.transition(item.id, ItemStatus.NEEDS_REVIEW, event="review",
                                      detail={"note": "中断期间目标位置被占用"},
                                      review_reason=ReviewReason.CONFLICT)
        if outcomes is not None:
            for item in self.items.with_status(ItemStatus.BUILDING):
                if not self.libraries.get(item.library_id).library_dir.is_dir():
                    continue  # unmounted: decide once the library is reachable again
                entry = journal.get(item.id)
                final = (self.libraries.get(item.library_id).library_dir / item.target_path
                         if item.target_path else None)
                if entry is not None and entry.phase == "published" and final is not None and final.exists():
                    # Crashed after the journal said "published" but before the item did.
                    self.items.transition(item.id, ItemStatus.PUBLISHED, event="published",
                                          detail={"note": "重启后已恢复"})
                    self._dispose(self.libraries.get(item.library_id), self.items.get(item.id))
                else:  # crashed before the journal row was written
                    self.items.transition(item.id, ItemStatus.READY, event="recovered",
                                          detail={"note": "中断于准备阶段"})
        for library in self.libraries.all():
            if not library.library_dir.is_dir():
                continue
            try:
                publisher.sweep_staging(library.library_dir)
            except OSError:
                pass

    # ---- helpers ----------------------------------------------------------------------------

    def _review(self, item_id: int, reason: ReviewReason, event: str, detail: dict) -> None:
        self.items.transition(item_id, ItemStatus.NEEDS_REVIEW, event=event, detail=detail, review_reason=reason)

    def _fail(self, item_id: int, error: Optional[BaseException] = None, *, message: Optional[str] = None) -> None:
        """Mark the item failed with a sentence a person can act on; the technical error goes in ``raw``."""
        if message is None:
            message = failure.describe(error)
        detail = {"error": message}
        if error is not None:
            detail["raw"] = failure.raw(error)
            log.warning("整理出错（%s）：%s", message, detail["raw"])
        try:
            self.items.transition(item_id, ItemStatus.FAILED, event="failed", detail=detail, error=message)
        except Exception:
            self.items.add_event(item_id, "failed", detail)

    def _counts(self, item_ids: Sequence[int]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item_id in item_ids:
            status = self.items.get(item_id).status.value
            counts[status] = counts.get(status, 0) + 1
        return counts


def _parts_under(root: Path, path: Path) -> Tuple[str, ...]:
    """``path`` relative to ``root``; a parent respelled by :func:`locate_source` still counts as inside."""
    try:
        return Path(path).relative_to(root).parts
    except ValueError:
        return Path(unicodedata.normalize("NFC", str(path))).relative_to(unicodedata.normalize("NFC", str(root))).parts


def _folder_of(library: Library, path: Path, root: Optional[Path]) -> Optional[str]:
    """The first folder under the source dir. A file dropped by itself reads the folder it was dropped from:
    ``Vol.01.cbz`` says nothing without it."""
    parts = _parts_under(root if root is not None else library.source_dir, path)
    if len(parts) > 1:
        return unicodedata.normalize("NFC", parts[0])
    return unicodedata.normalize("NFC", root.name) if root is not None and root.name else None


def entry_for(library: Library, path: Path, root: Optional[Path] = None) -> SourceEntry:
    """Rebuild the scan entry for a stored item (used by replan and execute)."""
    path = Path(path)
    folder = _folder_of(library, path, root)
    if library.kind == "novel":
        return SourceEntry(path, "epub", folder, root)
    if path.is_dir():
        return SourceEntry(path, "folder", folder, root)
    return SourceEntry(path, "pdf" if path.suffix.casefold() == ".pdf" else "archive", folder, root)


def locate_source(path: Path) -> Optional[Path]:
    """``path`` if it exists, else the same path spelled in another Unicode form (macOS writes names
    decomposed, other tools composed), else None."""
    path = Path(path)
    if os.path.lexists(path):
        return path
    current = Path(path.anchor)
    for part in path.parts[1:]:
        candidate = current / part
        if not os.path.lexists(candidate):
            wanted = unicodedata.normalize("NFC", part)
            try:
                names = os.listdir(current)
            except OSError:
                return None
            match = next((name for name in names if unicodedata.normalize("NFC", name) == wanted), None)
            if match is None:
                return None
            candidate = current / match
        current = candidate
    return current


def _is_loose_drop(entry: SourceEntry) -> bool:
    return entry.root is not None and len(_parts_under(entry.root, entry.path)) == 1


def review_group(library: Library, path: Path, root: Optional[Path] = None) -> str:
    """The unit a review decision covers: the first folder under the source dir, or the file itself.

    A file dropped by itself tells the AI which folder it came from, but that folder groups nothing: Downloads
    holds anything. It starts alone, and joins the work the AI names (see :meth:`Organizer._recognize_and_match`).
    """
    path = Path(path)
    if root is not None and len(_parts_under(root, path)) == 1:
        return unicodedata.normalize("NFC", path.name)
    folder = _folder_of(library, path, root)
    return folder if folder is not None else unicodedata.normalize("NFC", path.name)


def validate_choices(*, title=None, edition=None, subject: Optional[SubjectRef] = None,
                     volumes: Mapping[int, str] = {}, sources: Optional[Sequence[str]] = None) -> None:
    """Reject a review choice before anything changes; messages are for the user."""
    for label, value in (("系列名", title), ("版本", edition)):
        if value in (None, ""):
            continue
        if not isinstance(value, str) or not _safe_name(value):
            raise ValueError("{0}不能为空，也不能含有 / 或首尾空格：{1}".format(label, value))
    if subject is not None:
        if not isinstance(subject, SubjectRef) or not subject.source or not str(subject.id).strip():
            raise ValueError("条目的来源和编号都不能为空")
        if sources is not None and subject.source not in sources:
            raise ValueError("没有这个数据源：{0}".format(subject.source))
    for volume in volumes.values():
        parse_volume_text(volume)


def _ref_json(subject: Optional[SubjectRef]) -> Optional[dict]:
    return subject.to_json() if subject is not None else None


def _needs_ai(item: Item) -> bool:
    """Review choices that name both the series and the volume leave nothing for the AI to read."""
    overrides = item.overrides or {}
    return not ((overrides.get("title") or overrides.get("subject") or overrides.get("bgm"))
                and overrides.get("volume"))


def _name_in_folder(library: Library, entry: SourceEntry) -> str:
    """What the AI is shown: the path under the series folder, or the file name for loose files."""
    parts = _parts_under(entry.root if entry.root is not None else library.source_dir, entry.path)
    return unicodedata.normalize("NFC", "/".join(parts[1:] if len(parts) > 1 else parts))


def _library_names(library_dir: Path) -> Tuple[List[str], List[str]]:
    """Series folders already in the library, and the editions their names carry (``迷宫饭[bili电子版]``)."""
    series, editions = [], []
    try:
        names = sorted(entry.name for entry in os.scandir(library_dir)
                       if entry.is_dir() and not entry.name.startswith(".") and entry.name != STATE_DIR)
    except OSError:
        return series, editions
    for name in names:
        name = unicodedata.normalize("NFC", name)
        series.append(name)
        if name.endswith("]") and "[" in name:
            edition = name[name.rindex("[") + 1:-1]
            if edition and edition not in editions:
                editions.append(edition)
    return series, editions


def _part_name(title: str, base_title: str) -> str:
    """What the sub-series adds to the original's name: 外传 for 迷宫饭 外传."""
    if title.startswith(base_title):
        return title[len(base_title):].strip(" ·・:：-—~～") or title
    return title


def _plain_number(number: Decimal) -> str:
    return format(number.normalize(), "f")


def _as_special(file: FileReading, part: str) -> FileReading:
    """A file of a merged sub-series: named after the part, so its Vol.01 does not clash with the original's."""
    if file.unit == "special" or file.number is None:
        label = "{0} {1}".format(part, file.label).strip()
    elif file.unit == "chapter":
        label = "{0} 第{1}话".format(part, _plain_number(file.number))
    elif file.end is not None and file.end > file.number:
        label = "{0} {1}-{2}".format(part, _plain_number(file.number), _plain_number(file.end))
    else:
        label = "{0} {1}".format(part, _plain_number(file.number))
    number = Decimal(max(int(file.number), 1)) if file.number is not None else Decimal(1)
    return FileReading("special", number, None, label, file.confidence)


def _reading_json(reading: Reading) -> dict:
    series, file = reading.series, reading.file
    confidence = min(series.confidence, file.confidence) if file is not None else series.confidence
    return {"subject_id": None, "title": series.title, "edition": series.edition, "confidence": confidence,
            "reason": series.reason, "meets_threshold": False, "call_id": reading.call_id, "problem": reading.problem}


def _suggestion_json(suggestion) -> dict:
    return {key: getattr(suggestion, key) for key in
            ("subject_id", "title", "edition", "confidence", "reason", "meets_threshold", "call_id", "problem")}


def _parsed_json(parse: ParseResult, reading: Optional[Reading]) -> dict:
    data = {
        "title_hint": parse.title_hint,
        "edition": parse.edition,
        "volume": parse.volume.key() if parse.volume is not None else None,
        "search_titles": list(parse.search_titles),
        "details": {key: list(value) if isinstance(value, tuple) else value
                    for key, value in dict(parse.details).items()},
    }
    if reading is not None and reading.series is not None:
        data["ai"] = {"confidence": reading.series.confidence, "reason": reading.series.reason,
                      "file_confidence": reading.file.confidence if reading.file else None,
                      "call_id": reading.call_id}
    return data
