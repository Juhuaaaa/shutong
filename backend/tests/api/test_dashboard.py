import shutil
import unittest

from .helpers import ApiCase


class DashboardTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.login()
        self.manga = self.make_library()
        for name in ("迷宫饭/迷宫饭 Vol.01.zip", "迷宫饭/迷宫饭 Vol.02.zip", "迷宫饭/迷宫饭 Vol.03.zip", "[]x/Vol.01.zip"):
            self.zip(name)
        self.client.post("/api/libraries/{0}/scan".format(self.manga["id"]))
        novel_source, novel_library = self.root / "novel-source", self.root / "novel-library"
        novel_source.mkdir()
        novel_library.mkdir()
        self.novel = self.make_library(name="轻小说", kind="novel", source_dir=str(novel_source),
                                       library_dir=str(novel_library))

    def dashboard(self):
        response = self.client.get("/api/dashboard")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_library_statistics(self):
        manga, novel = self.dashboard()["libraries"]
        self.assertEqual((manga["name"], manga["kind"], manga["series"], manga["volumes"], manga["month_new"],
                          manga["planned"], manga["needs_review"], manga["failed"], manga["available"]),
                         ("漫画", "manga", 1, 3, 3, 0, 1, 0, True))
        self.assertEqual((novel["name"], novel["series"], novel["volumes"], novel["available"]), ("轻小说", 0, 0, True))

    def test_month_new_counts_only_this_month(self):
        with self.app.state.db.connect() as connection:
            connection.execute("UPDATE item_events SET at = '2020-01-01T00:00:00+00:00' WHERE kind = 'published'"
                               " AND item_id = (SELECT min(item_id) FROM item_events WHERE kind = 'published')")
        manga = self.dashboard()["libraries"][0]
        self.assertEqual((manga["volumes"], manga["month_new"]), (3, 2))

    def test_recent_groups_by_source_folder(self):
        [recent] = self.dashboard()["recent"]
        self.assertEqual((recent["library_id"], recent["group_key"], recent["series"], recent["subject_id"],
                          recent["published"]), (self.manga["id"], "迷宫饭", "迷宫饭", 133315, 3))
        self.assertEqual(recent["image"], "https://api.bgm.tv/v0/subjects/133315/image?type=common")

    def test_recent_keeps_eight(self):
        with self.app.state.db.connect() as connection:
            item_id = connection.execute("SELECT min(id) FROM items WHERE status = 'published'").fetchone()[0]
            for n in range(10):
                connection.execute("INSERT INTO items(library_id, source_path, fingerprint, status, group_key,"
                                   " created_at, updated_at) VALUES (?, ?, ?, 'published', ?, 't', 't')",
                                   (self.manga["id"], "/s/g{0}/1.zip".format(n), "fp{0}".format(n), "g{0}".format(n)))
                connection.execute("INSERT INTO item_events(item_id, at, kind, detail) VALUES"
                                   " (last_insert_rowid(), ?, 'published', '{}')", ("2030-01-0{0}T00:00:00+00:00".format(n % 9 + 1),))
        recent = self.dashboard()["recent"]
        self.assertEqual(len(recent), 8)
        self.assertNotIn("迷宫饭", [group["group_key"] for group in recent])
        self.assertIsNotNone(item_id)

    def test_jobs_and_storage(self):
        data = self.dashboard()
        self.assertEqual([job["kind"] for job in data["jobs"]], ["scan"])
        self.assertLessEqual(len(data["jobs"]), 5)
        [storage] = data["storage"]  # both libraries live on the same file system
        self.assertGreater(storage["total"], 0)
        self.assertTrue(0 < storage["used"] <= storage["total"] and 0 < storage["free"] <= storage["total"])

    def test_unavailable_library(self):
        shutil.rmtree(self.root / "novel-library")
        novel = self.dashboard()["libraries"][1]
        self.assertEqual((novel["available"], novel["series"]), (False, 0))
        self.assertNotIn(str(self.root / "novel-library"), [entry["path"] for entry in self.dashboard()["storage"]])


    def test_filesystem_is_read_without_holding_the_database(self):
        import sqlite3
        from unittest import mock
        from shutong.api.routes import dashboard as module
        real = module._series_count
        path = self.app.state.db.path

        def probe(directory):
            connection = sqlite3.connect(path, timeout=0)
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
            finally:
                connection.close()
            return real(directory)

        with mock.patch.object(module, "_series_count", side_effect=probe):
            self.assertEqual(self.dashboard()["libraries"][0]["series"], 1)

if __name__ == "__main__":
    unittest.main()
