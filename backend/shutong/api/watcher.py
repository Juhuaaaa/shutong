"""Watch the source dirs of libraries that ask for it, and scan once new files have settled.

Every ``interval`` seconds the source dir is listed (names, sizes, modification times; no file is read).
A scan starts when the listing differs from the one last scanned and has not changed since the previous
look, so a file still being downloaded is left alone until it stops growing.
"""
import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Dict, Optional

from shutong.store.records import LibraryStore

log = logging.getLogger("shutong.watch")

DEFAULT_INTERVAL = 300  # seconds


def snapshot(root: Path) -> Optional[str]:
    """A digest of what is in ``root``; None when it cannot be read (unmounted share)."""
    digest = hashlib.sha256()
    try:
        for directory, folders, files in os.walk(root):
            folders[:] = sorted(folder for folder in folders if not folder.startswith("."))
            for name in sorted(files):
                if name.startswith("."):
                    continue  # hidden files, including uploads in progress
                path = os.path.join(directory, name)
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                digest.update("{0}\0{1}\0{2}\n".format(os.path.relpath(path, root), stat.st_size,
                                                       stat.st_mtime_ns).encode("utf-8", "surrogateescape"))
    except OSError:
        return None
    if not Path(root).is_dir():
        return None
    return digest.hexdigest()


class SourceWatcher:
    def __init__(self, app, interval: float = DEFAULT_INTERVAL) -> None:
        self.app = app
        self.interval = interval
        self._seen: Dict[int, str] = {}  # library id -> listing at the previous look
        self._scanned: Dict[int, str] = {}  # library id -> listing the last scan started from
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="shutong-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception:  # one bad look must not end watching
                log.exception("检查来源目录出错")

    def tick(self) -> None:
        from shutong.api.routes.libraries import submit_scan  # the routes import the app's modules

        watched = {library.id: library for library in LibraryStore(self.app.state.db).all()
                   if library.watch and not library.source_managed}
        for library_id in list(self._seen):
            if library_id not in watched:  # watch turned off: start afresh if it comes back on
                self._seen.pop(library_id, None)
                self._scanned.pop(library_id, None)
        for library in watched.values():
            listing = snapshot(library.source_dir)
            if listing is None:
                continue
            previous = self._seen.get(library.id)
            self._seen[library.id] = listing
            if listing != previous:
                continue  # first look, or still changing: wait for it to settle
            if listing == self._scanned.get(library.id) or self._busy(library.id):
                continue
            if self.app.state.services_factory(self.app.state.db).ai is None:
                continue  # scanning needs the AI; nothing to do until it is set up
            self._scanned[library.id] = listing
            log.info("来源目录有新内容，自动扫描：%s", library.name)
            submit_scan(self.app, library, "watch")

    def _busy(self, library_id: int) -> bool:
        return any(job.library_id == library_id and job.state in ("queued", "running")
                   for job in self.app.state.jobs.recent(200))
