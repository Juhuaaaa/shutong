import time
import unittest

from shutong.api.app import create_app
from shutong.engine.organizer import review_group
from shutong.store.records import ItemStore, LibraryStore

from .helpers import ApiCase


class HistoryRoutesTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.login()
        self.library = self.make_library()
        for name in ("迷宫饭/迷宫饭 Vol.02.zip", "迷宫饭/迷宫饭 Vol.01.zip", "迷宫饭/迷宫饭 Vol.10.zip", "[]x/Vol.01.zip"):
            self.zip(name)
        self.client.post("/api/libraries/{0}/scan".format(self.library["id"]))

    def history(self, **params):
        response = self.client.get("/api/history/groups", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_one_record_per_source_folder(self):
        page = self.history(library_id=self.library["id"])
        self.assertEqual(page["total"], 2)
        by_folder = {group["folder"]: group for group in page["groups"]}
        dungeon = by_folder["迷宫饭"]
        self.assertEqual((dungeon["total"], dungeon["counts"], dungeon["series"], dungeon["subject_id"]),
                         (3, {"published": 3}, "迷宫饭", "133315"))
        self.assertEqual(len(dungeon["item_ids"]), 3)
        self.assertEqual(by_folder["[]x"]["counts"], {"needs_review": 1})

    def test_newest_first_and_paging(self):
        store = ItemStore(self.app.state.db)
        [first] = [group for group in self.history()["groups"] if group["folder"] == "[]x"]
        store.add_event(first["item_ids"][0], "note")
        with self.app.state.db.connect() as connection:
            connection.execute("UPDATE items SET updated_at = '2999-01-01T00:00:00+00:00' WHERE id = ?",
                               (first["item_ids"][0],))
        self.assertEqual([group["folder"] for group in self.history()["groups"]], ["[]x", "迷宫饭"])
        page = self.history(limit=1, offset=1)
        self.assertEqual(([group["folder"] for group in page["groups"]], page["total"]), (["迷宫饭"], 2))

    def test_filters(self):
        self.assertEqual([group["folder"] for group in self.history(status="needs_review")["groups"]], ["[]x"])
        self.assertEqual([group["folder"] for group in self.history(q="迷宫")["groups"]], ["迷宫饭"])
        self.assertEqual(self.history(q="nothing")["total"], 0)

    def test_counts_and_filters_published_files_without_metadata(self):
        dungeon = [group for group in self.history()["groups"] if group["folder"] == "迷宫饭"][0]
        self.assertEqual(dungeon["missing_metadata"], 0)
        self.assertEqual(self.history(missing_metadata="true")["total"], 0)
        with self.app.state.db.connect() as connection:
            connection.execute("UPDATE items SET subject_id = NULL WHERE id IN (?, ?)", dungeon["item_ids"][:2])
        page = self.history(missing_metadata="true")
        self.assertEqual([(group["folder"], group["missing_metadata"]) for group in page["groups"]], [("迷宫饭", 2)])
        self.assertEqual(page["total"], 1)
        # Review items have no subject yet either, but they are not organized, so they are not "missing".
        review = [group for group in self.history()["groups"] if group["folder"] == "[]x"][0]
        self.assertEqual(review["missing_metadata"], 0)

    def test_filters_for_spot_checks(self):
        dungeon = [group for group in self.history()["groups"] if group["folder"] == "迷宫饭"][0]
        self.assertEqual(self.history(ai_picked="true")["total"], 0)
        self.assertEqual(self.history(source="anilist")["total"], 0)
        self.assertEqual([group["folder"] for group in self.history(source="bangumi")["groups"]], ["迷宫饭"])
        with self.app.state.db.connect() as connection:
            connection.execute("INSERT INTO item_events(item_id, at, kind, detail) VALUES (?, 't', 'ai_adopted', '{}')",
                               (dungeon["item_ids"][0],))
            connection.execute("UPDATE items SET subject_source = 'anilist' WHERE id = ?", (dungeon["item_ids"][1],))
        self.assertEqual([group["folder"] for group in self.history(ai_picked="true")["groups"]], ["迷宫饭"])
        self.assertEqual([group["folder"] for group in self.history(source="anilist")["groups"]], ["迷宫饭"])
        self.assertEqual(self.history(source="anilist", status="needs_review")["total"], 0)

    def test_series_falls_back_to_the_library_folder(self):
        dungeon = [group for group in self.history()["groups"] if group["folder"] == "迷宫饭"][0]
        with self.app.state.db.connect() as connection:  # records imported from the old tool carry no plan
            connection.executemany("UPDATE items SET plan = '{}', target_path = '迷宫饭[东立电子版]/Vol.01.cbz'"
                                   " WHERE id = ?", [(item_id,) for item_id in dungeon["item_ids"]])
        dungeon = [group for group in self.history()["groups"] if group["folder"] == "迷宫饭"][0]
        self.assertEqual(dungeon["series"], "迷宫饭[东立电子版]")

    def test_group_items_sorted_by_volume(self):
        response = self.client.get("/api/history/groups/{0}/迷宫饭".format(self.library["id"]))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["source_name"] for item in response.json()],
                         ["迷宫饭 Vol.01.zip", "迷宫饭 Vol.02.zip", "迷宫饭 Vol.10.zip"])
        self.assertEqual(self.client.get("/api/history/groups/{0}/none".format(self.library["id"])).json(), [])

    def test_group_items_by_status(self):
        response = self.client.get("/api/history/groups/{0}/[]x".format(self.library["id"]), params={"status": "needs_review"})
        self.assertEqual([item["status"] for item in response.json()], ["needs_review"])
        none = self.client.get("/api/history/groups/{0}/迷宫饭".format(self.library["id"]), params={"status": "needs_review"})
        self.assertEqual(none.json(), [])

    def test_backfill_on_start_matches_review_group(self):
        with self.app.state.db.connect() as connection:
            connection.execute("UPDATE items SET group_key = NULL")
        app = create_app(self.data_dir, inline_jobs=True, services_factory=self.services)
        self.addCleanup(app.state.jobs.stop)
        library = LibraryStore(app.state.db).get(self.library["id"])
        with app.state.db.connect() as connection:
            rows = connection.execute("SELECT source_path, group_key FROM items").fetchall()
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertEqual(row["group_key"], review_group(library, row["source_path"]))


class ReviewSpeedTests(ApiCase):
    def test_review_groups_read_one_item_per_group(self):
        self.login()
        library = self.make_library()
        stamp = "2026-10-30T00:00:00+00:00"
        with self.app.state.db.connect() as connection:
            for group in range(90):
                for volume in range(34):
                    connection.execute(
                        "INSERT INTO items(library_id, source_path, fingerprint, status, review_reason, parsed,"
                        " group_key, created_at, updated_at) VALUES (?, ?, ?, 'needs_review', 'volume', ?, ?, ?, ?)",
                        (library["id"], "{0}/[]g{1}/{2}.zip".format(library["source_dir"], group, volume),
                         "fp-{0}-{1}".format(group, volume), '{"title_hint": "g"}', "[]g{0}".format(group),
                         stamp, stamp))
        connections = []
        real = type(self.app.state.db).connect

        def counted(db):
            connections.append(1)
            return real(db)

        type(self.app.state.db).connect = counted
        self.addCleanup(setattr, type(self.app.state.db), "connect", real)
        started = time.perf_counter()
        groups = self.client.get("/api/review/groups", params={"library_id": library["id"]}).json()
        elapsed = time.perf_counter() - started
        self.assertEqual(len(groups), 90)
        self.assertLessEqual(len(connections), 5)  # a fixed number of queries, not two per group
        self.assertEqual(groups[0]["count"], 34)
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
