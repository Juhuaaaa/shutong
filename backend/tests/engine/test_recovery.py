import os
import unittest
from unittest import mock

from shutong.engine.publish import Publisher
from shutong.store.journal import JournalStore

from .support import EngineTestCase


class Killed(BaseException):
    """Stands in for the process dying mid-publication."""


CRASH_POINTS = ["after_start", "after_mark_staged", "after_move", "after_unlink_staged"]


class RecoveryTests(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.journal = JournalStore(self.db)
        self.staging_dir = self.lib / ".shutong" / "staging"

    def _crash(self, point, item, final):
        pub = Publisher(self.journal)
        staged = pub.start(item, self.lib, final)
        staged.write_bytes(b"cbz")
        if point == "after_start":
            return
        patches = {
            "after_mark_staged": mock.patch("shutong.engine.publish.no_overwrite_move",
                                            side_effect=Killed),
            "after_move": mock.patch.object(JournalStore, "mark_published", side_effect=Killed),
            "after_unlink_staged": mock.patch("shutong.engine.publish.os.unlink",
                                              side_effect=Killed),
        }
        with patches[point], self.assertRaises(Killed):
            pub.commit(item, verify=lambda path: None)

    def test_crash_at_each_point_leaves_consistent_state(self):
        expected = {"after_start": "reset", "after_mark_staged": "reset",
                    "after_move": "published", "after_unlink_staged": "published"}
        for number, point in enumerate(CRASH_POINTS):
            with self.subTest(point=point):
                if point == "after_unlink_staged" and os.name == "nt":
                    self.skipTest("rename has no separate unlink on Windows")
                item = self.make_item("{0}.zip".format(number))
                final = self.lib / "系列" / "系列 Vol.{0:02d}.cbz".format(number)
                self._crash(point, item, final)

                restarted = Publisher(JournalStore(self.db))
                outcomes = restarted.recover()
                restarted.sweep_staging(self.lib)

                self.assertEqual([(o.item_id, o.outcome) for o in outcomes],
                                 [(item, expected[point])])
                if expected[point] == "published":
                    self.assertEqual(final.read_bytes(), b"cbz")
                    self.assertEqual(self.journal.get(item).phase, "published")
                else:
                    self.assertFalse(final.exists())
                    self.assertIsNone(self.journal.get(item))
                self.assertEqual(list(self.staging_dir.iterdir()), [])
                self.assertEqual(self.journal.pending(), [])

    def test_foreign_file_at_target_is_conflict_and_untouched(self):
        item = self.make_item()
        final = self.lib / "系列" / "系列 Vol.01.cbz"
        self._crash("after_mark_staged", item, final)
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b"someone else")
        outcomes = Publisher(self.journal).recover()
        self.assertEqual(outcomes[0].outcome, "conflict")
        self.assertEqual(final.read_bytes(), b"someone else")
        self.assertIsNone(self.journal.get(item))

    def test_target_appearing_while_building_is_conflict(self):
        item = self.make_item()
        final = self.lib / "系列" / "系列 Vol.01.cbz"
        self._crash("after_start", item, final)
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b"cbz")  # same bytes, but we never verified ours
        self.assertEqual(Publisher(self.journal).recover()[0].outcome, "conflict")
        self.assertEqual(final.read_bytes(), b"cbz")

    def test_sweep_removes_orphan_staging_files(self):
        self.staging_dir.mkdir(parents=True)
        (self.staging_dir / "99-dead.cbz").write_bytes(b"x")
        self.assertEqual(Publisher(self.journal).sweep_staging(self.lib), 1)
        self.assertEqual(list(self.staging_dir.iterdir()), [])

    def test_sweep_keeps_files_of_pending_publications(self):
        item = self.make_item()
        staged = Publisher(self.journal).start(item, self.lib, self.lib / "系列" / "a.cbz")
        staged.write_bytes(b"in progress")
        self.assertEqual(Publisher(self.journal).sweep_staging(self.lib), 0)
        self.assertTrue(staged.exists())


if __name__ == "__main__":
    unittest.main()
