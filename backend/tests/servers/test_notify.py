from pathlib import Path
import tempfile
import unittest

from shutong.servers.notify import notify_published
from shutong.store.db import Database
from shutong.store.records import ItemStore, LibraryStore
from shutong.store.servers import ServerStore

from ..api.helpers import FakeServer


class NotifyTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.db = Database(Path(self._directory.name) / "shutong.db")
        self.db.migrate()
        servers, libraries = ServerStore(self.db), LibraryStore(self.db)
        self.server = servers.create("kavita", "家里", "http://k", "u", "p")
        self.manga = libraries.update(libraries.create("漫画", "manga", Path("/s1"), Path("/l1")).id,
                                      server_id=self.server.id, server_library_id=3)
        self.novel = libraries.update(libraries.create("轻小说", "novel", Path("/s2"), Path("/l2")).id,
                                      server_id=self.server.id, server_library_id=7)
        self.loose = libraries.create("散", "manga", Path("/s3"), Path("/l3"))
        self.items = ItemStore(self.db)
        self.error = None
        FakeServer.instances = []

    def item(self, library, name):
        return self.items.create(library.id, Path("/s") / name, "v1:" + name).id

    def notify(self, ids, **kwargs):
        return notify_published(self.db, ids, server_factory=lambda record: FakeServer(record, self.error), **kwargs)

    def calls(self):
        return [call for server in FakeServer.instances for call in server.calls]

    def test_one_scan_per_server_library(self):
        result = self.notify([self.item(self.manga, "a"), self.item(self.manga, "b"), self.item(self.novel, "c"),
                              self.item(self.loose, "d")])
        self.assertEqual(sorted(self.calls()), [("scan", 3), ("scan", 7)])
        self.assertEqual(sorted(entry["library_id"] for entry in result["scanned"]), [3, 7])
        self.assertEqual(result["errors"], [])

    def test_disabled_server_is_skipped(self):
        ServerStore(self.db).update(self.server.id, enabled=False)
        self.notify([self.item(self.manga, "a")])
        self.assertEqual(self.calls(), [])

    def test_errors_are_collected_not_raised(self):
        self.error = "连不上 Kavita：http://k"
        result = self.notify([self.item(self.manga, "a")])
        self.assertEqual(result["errors"], ["家里：连不上 Kavita：http://k"])
        self.assertEqual(result["scanned"], [])

    def test_refresh_series_after_the_scan(self):
        item = self.item(self.manga, "a")
        result = self.notify([item], refresh_series=[(self.manga.id, "迷宫饭")])
        self.assertEqual(self.calls(), [("scan", 3), ("refresh", 3, "迷宫饭")])
        self.assertEqual(result["refreshed"], ["迷宫饭"])

    def test_nothing_published_contacts_nobody(self):
        self.assertEqual(self.notify([]), {"scanned": [], "refreshed": [], "errors": []})
        self.assertEqual(FakeServer.instances, [])

    def test_unexpected_exception_is_reported(self):
        def broken(record):
            raise RuntimeError("bug")

        result = notify_published(self.db, [self.item(self.manga, "a")], server_factory=broken)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("家里", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
