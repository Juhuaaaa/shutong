"""Shared fixtures for engine tests: a migrated database with one library."""
from pathlib import Path
import tempfile
import unittest

from shutong.store.db import Database
from shutong.store.records import ItemStore, LibraryStore


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.source_root = self.root / "source"
        self.lib = self.root / "library"
        self.source_root.mkdir()
        self.lib.mkdir()
        self.db = Database(self.root / "shutong.db")
        self.db.migrate()
        self.library = LibraryStore(self.db).create("漫画", "manga", self.source_root, self.lib)
        self.items = ItemStore(self.db)

    def make_item(self, name: str = "a.zip") -> int:
        return self.items.create(self.library.id, self.source_root / name, "v1:" + name).id
