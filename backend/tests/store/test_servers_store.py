from pathlib import Path
import sqlite3
import tempfile
import unittest

from shutong.store.db import Database
from shutong.store.records import LibraryStore
from shutong.store.servers import ServerStore


class ServerStoreTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.db = Database(Path(self._directory.name) / "shutong.db")
        self.db.migrate()
        self.store = ServerStore(self.db)
        self.libraries = LibraryStore(self.db)

    def test_crud(self):
        server = self.store.create("kavita", "家里", "http://kavita:5000", "user", "pw")
        self.assertEqual((server.name, server.enabled), ("家里", True))
        changed = self.store.update(server.id, password="new", enabled=False)
        self.assertEqual((changed.password, changed.enabled, changed.username), ("new", False, "user"))
        self.assertEqual([entry.id for entry in self.store.all()], [server.id])
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create("kavita", "家里", "http://x", "", "")
        self.store.delete(server.id)
        with self.assertRaises(KeyError):
            self.store.get(server.id)

    def test_library_mapping_cleared_when_server_deleted(self):
        library = self.libraries.create("漫画", "manga", Path("/s"), Path("/l"))
        self.assertEqual((library.server_id, library.server_library_id), (None, None))
        server = self.store.create("kavita", "家里", "http://kavita:5000", "user", "pw")
        mapped = self.libraries.update(library.id, server_id=server.id, server_library_id=3)
        self.assertEqual((mapped.server_id, mapped.server_library_id), (server.id, "3"))
        self.store.delete(server.id)
        self.assertIsNone(self.libraries.get(library.id).server_id)


if __name__ == "__main__":
    unittest.main()
