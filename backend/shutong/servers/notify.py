"""After a batch is published: one scan per media-server library, then cover refreshes for redone series.

Nothing here may fail the batch: the files are already published, so problems are only reported.
"""
import logging
from typing import Callable, Dict, Iterable, List, Sequence, Tuple

from shutong.servers.base import MediaServer, ServerError
from shutong.store.db import Database
from shutong.store.records import ItemStore, LibraryStore
from shutong.store.servers import ServerRecord, ServerStore

log = logging.getLogger("shutong.kavita")


def notify_published(db: Database, item_ids: Sequence[int], *,
                     server_factory: Callable[[ServerRecord], MediaServer],
                     refresh_series: Iterable[Tuple[int, str]] = ()) -> dict:
    result = {"scanned": [], "refreshed": [], "errors": []}
    if not item_ids:
        return result
    items, libraries, servers = ItemStore(db), LibraryStore(db), ServerStore(db)
    targets: Dict[Tuple[int, int], List[int]] = {}  # (server id, server library id) -> our library ids
    for library_id in sorted({items.get(item_id).library_id for item_id in item_ids}):
        library = libraries.get(library_id)
        if library.server_id is None or library.server_library_id is None:
            continue
        targets.setdefault((library.server_id, library.server_library_id), []).append(library_id)
    refresh = list(refresh_series)
    for (server_id, server_library_id), library_ids in sorted(targets.items()):
        record = servers.get(server_id)
        if not record.enabled:
            continue
        try:
            server = server_factory(record)
            server.scan_library(server_library_id)
            result["scanned"].append({"server": record.name, "library_id": server_library_id})
            log.info("已通知 %s 扫描库 %s", record.name, server_library_id)
            for library_id, series in refresh:
                if library_id in library_ids and server.refresh_series(server_library_id, series):
                    result["refreshed"].append(series)
        except ServerError as error:
            result["errors"].append("{0}：{1}".format(record.name, error))
            log.warning("通知 %s 失败：%s", record.name, error)
        except Exception as error:  # a bug talking to the server must not fail a published batch
            result["errors"].append("{0}：通知失败（{1}: {2}）".format(record.name, type(error).__name__, error))
            log.exception("通知 %s 出错", record.name)
    return result


def redone_series(db: Database, item_ids: Sequence[int]) -> List[Tuple[int, str]]:
    """Series whose published file was replaced by a reorganize: Kavita keeps the old cover for those."""
    store, found = ItemStore(db), []
    for item_id in item_ids:
        kinds = [event.kind for event in store.events(item_id)]
        published = [index for index, kind in enumerate(kinds) if kind in ("published", "claimed", "imported")]
        previous = published[-2] if len(published) > 1 else -1
        latest = published[-1] if published else -1
        if any(kind in ("target_deleted", "target_trashed") for kind in kinds[previous + 1:latest]):
            item = store.get(item_id)
            series = item.plan.get("series")
            if series and (item.library_id, series) not in found:
                found.append((item.library_id, series))
    return found
