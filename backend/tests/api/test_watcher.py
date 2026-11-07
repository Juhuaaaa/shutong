"""Watching a source dir: a change that has settled starts a scan; nothing else does."""
import unittest

from shutong.api.watcher import SourceWatcher

from .helpers import ApiCase


class WatcherTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.login()
        self.watcher = SourceWatcher(self.app, interval=300)

    def scans(self):
        return [job for job in self.app.state.jobs.recent() if job.kind == "scan"]

    def test_settled_new_files_are_scanned_once(self):
        library = self.make_library(watch=True)
        self.assertTrue(library["watch"])
        self.watcher.tick()  # first look: remembers the folder
        self.watcher.tick()  # unchanged since: catch up with whatever arrived while shut down
        self.assertEqual(len(self.scans()), 1)
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.watcher.tick()  # changed: maybe still downloading, wait
        self.assertEqual(len(self.scans()), 1)
        self.watcher.tick()  # settled: scan
        self.assertEqual(len(self.scans()), 2)
        self.assertTrue((self.root / "library" / "迷宫饭" / "迷宫饭 Vol.01.cbz").exists())
        runs = self.client.get("/api/libraries/{0}/runs".format(library["id"])).json()
        self.assertEqual(runs[0]["trigger"], "watch")
        self.watcher.tick()
        self.assertEqual(len(self.scans()), 2)

    def test_libraries_without_watch_are_left_alone(self):
        self.make_library()
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        for _ in range(3):
            self.watcher.tick()
        self.assertEqual(self.scans(), [])

    def test_turning_watch_on_later(self):
        library = self.make_library()
        response = self.client.patch("/api/libraries/{0}".format(library["id"]), json={"watch": True})
        self.assertEqual((response.status_code, response.json()["watch"]), (200, True))
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.watcher.tick()
        self.watcher.tick()
        self.assertEqual(len(self.scans()), 1)


if __name__ == "__main__":
    unittest.main()
