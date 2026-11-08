"""Files Shutong removes: gone for good on a server, into the system trash on the desktop."""
from pathlib import Path
import tempfile
import unittest

from shutong.engine import discard
from shutong.engine.disposal import DisposalContext, dispose_source
from shutong.engine.fingerprint import fingerprint
from shutong.engine.publish import Publisher
from shutong.store.db import Database
from shutong.store.journal import JournalStore
from shutong.store.records import ItemStore, LibraryStore


class Trash:
    def __init__(self, error=None):
        self.sent = []
        self.error = error

    def __call__(self, path):
        if self.error:
            raise self.error
        self.sent.append(Path(path).name)
        Path(path).unlink() if Path(path).is_file() else None


class DiscardTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.trash = Trash()
        self.addCleanup(discard.use_system_trash, False)

    def file(self, name, text="x"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_server_deletes_for_good(self):
        path = self.file("a.cbz")
        discard.use_system_trash(False, trasher=self.trash)
        self.assertEqual(discard.discard(path), "deleted")
        self.assertFalse(path.exists())
        self.assertEqual(self.trash.sent, [])

    def test_desktop_sends_to_the_trash(self):
        path = self.file("a.cbz")
        discard.use_system_trash(True, trasher=self.trash)
        self.assertEqual(discard.discard(path), "trashed")
        self.assertEqual(self.trash.sent, ["a.cbz"])

    def test_no_trash_on_that_drive_falls_back_to_deleting(self):
        path = self.file("a.cbz")
        discard.use_system_trash(True, trasher=Trash(error=OSError("no trash on this volume")))
        self.assertEqual(discard.discard(path), "deleted")
        self.assertFalse(path.exists())

    def test_missing_path_is_fine(self):
        discard.use_system_trash(True, trasher=self.trash)
        self.assertEqual(discard.discard(self.root / "gone.cbz"), "missing")

    def test_delete_policy_uses_the_trash_on_the_desktop(self):
        source = self.file("source/a.zip")
        discard.use_system_trash(True, trasher=self.trash)
        outcome = dispose_source(DisposalContext("delete", self.root / "source", None), source, fingerprint(source))
        self.assertEqual(outcome.outcome, "deleted")
        self.assertEqual(self.trash.sent, ["a.zip"])

    def test_overwriting_sends_the_old_file_to_the_trash(self):
        db = Database(self.root / "s.db")
        db.migrate()
        library = self.root / "library"
        final = library / "迷宫饭" / "迷宫饭 Vol.01.cbz"
        final.parent.mkdir(parents=True)
        final.write_text("old")
        discard.use_system_trash(True, trasher=self.trash)
        publisher = Publisher(JournalStore(db))
        owner = LibraryStore(db).create("漫画", "manga", self.root / "source", library)
        item = ItemStore(db).create(owner.id, self.root / "source" / "a.zip", "v1:a")
        staged = publisher.start(item.id, library, final, overwrite=True)
        staged.write_text("new")
        publisher.commit(item.id, lambda path: None, overwrite=True)
        self.assertEqual(final.read_text(), "new")
        self.assertEqual(self.trash.sent, ["迷宫饭 Vol.01.cbz"])


if __name__ == "__main__":
    unittest.main()
