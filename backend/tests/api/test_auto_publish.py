import unittest

from shutong.engine.states import ItemStatus
from shutong.store.records import ItemStore

from .helpers import DUNGEON, ApiCase, FakeServer
from ..engine.reader_ai import ReaderAi
from ..engine.test_match import FakeSource


class AutoPublishTests(ApiCase):
    """Whatever a job recognises for sure is published in the same job; the rest waits in review."""

    def setUp(self):
        super().setUp()
        self.ai = ReaderAi(unsure_series={"[]"})
        self.login()
        self.library = self.make_library()

    def job(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        return self.client.get("/api/jobs/{0}".format(response.json()["job_id"])).json()

    def statuses(self):
        items = self.client.get("/api/items", params={"library_id": self.library["id"]}).json()["items"]
        return sorted((item["source_name"], item["status"]) for item in items)

    def scan(self):
        return self.job(self.client.post("/api/libraries/{0}/scan".format(self.library["id"])))

    def test_scan_publishes_what_it_recognised(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("[]/Vol.01.zip")
        job = self.scan()
        self.assertEqual(self.statuses(), [("Vol.01.zip", "needs_review"), ("迷宫饭 Vol.01.zip", "published")])
        counts = job["result"]["counts"]
        self.assertEqual((counts["executed"], counts["planned"], counts["needs_review"]), (1, 0, 1))
        self.assertTrue((self.root / "library" / "迷宫饭" / "迷宫饭 Vol.01.cbz").exists())
        self.assertEqual((job["progress"]["done"], job["progress"]["total"]), (2, 2))

    def test_scan_tells_kavita_once(self):
        server = self.make_server()
        self.client.patch("/api/libraries/{0}".format(self.library["id"]),
                          json={"server_id": server["id"], "server_library_id": 3})
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.scan()
        self.assertEqual([call for server in FakeServer.instances for call in server.calls], [("scan", "3")])

    def test_scan_without_ai_is_refused(self):
        self.ai = None
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        response = self.client.post("/api/libraries/{0}/scan".format(self.library["id"]))
        self.assertEqual(response.status_code, 409)
        self.assertIn("AI", response.json()["detail"])
        self.assertEqual(self.statuses(), [])
        reidentify = self.client.post("/api/review/reidentify", json={"library_id": self.library["id"]})
        self.assertEqual(reidentify.status_code, 409)

    def test_reidentify_publishes_once_bangumi_answers(self):
        self.source = FakeSource(error=ValueError("malformed Bangumi response"))
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.scan()
        self.assertEqual(self.statuses(), [("迷宫饭 Vol.01.zip", "needs_review")])
        self.source = FakeSource([DUNGEON], subjects={133315: DUNGEON})
        job = self.job(self.client.post("/api/review/reidentify", json={"library_id": self.library["id"]}))
        self.assertEqual(self.statuses(), [("迷宫饭 Vol.01.zip", "published")])
        self.assertEqual((job["result"]["executed"], job["result"]["planned"]), (1, 0))

    def test_confirmed_review_is_published(self):
        self.zip("[]/Vol.01.zip")
        self.scan()
        ids = [item["id"] for item in self.client.get("/api/items", params={"library_id": self.library["id"]}).json()["items"]]
        job = self.job(self.client.post("/api/review/confirm", json={"item_ids": ids, "title": "迷宫饭", "bgm": 133315}))
        self.assertEqual(self.statuses(), [("Vol.01.zip", "published")])
        self.assertEqual(job["result"]["executed"], 1)

    def test_reorganize_publishes_again(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.scan()
        item = self.client.get("/api/items", params={"library_id": self.library["id"]}).json()["items"][0]
        job = self.job(self.client.post("/api/items/reorganize", json={"item_ids": [item["id"]], "title": "迷宫饭 新"}))
        self.assertEqual((job["result"]["deleted"], job["result"]["executed"]), (1, 1))
        detail = self.client.get("/api/items/{0}".format(item["id"])).json()
        self.assertEqual((detail["status"], detail["target_path"]), ("published", "迷宫饭 新/迷宫饭 新 Vol.01.cbz"))

    def test_retry_publishes_again(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.scan()
        item = self.client.get("/api/items", params={"library_id": self.library["id"]}).json()["items"][0]
        store = ItemStore(self.app.state.db)
        (self.root / "library" / item["target_path"]).unlink()
        for status in (ItemStatus.READY, ItemStatus.BUILDING, ItemStatus.FAILED):  # a build that broke
            store.transition(item["id"], status, event=status.value)
        job = self.job(self.client.post("/api/items/retry", json={"item_ids": [item["id"]]}))
        self.assertEqual(self.statuses(), [("迷宫饭 Vol.01.zip", "published")])
        self.assertEqual(job["result"]["executed"], 1)

    def test_scan_also_publishes_what_an_earlier_run_left_planned(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.scan()
        item = self.client.get("/api/items", params={"library_id": self.library["id"]}).json()["items"][0]
        store = ItemStore(self.app.state.db)
        (self.root / "library" / item["target_path"]).unlink()
        with self.app.state.db.connect() as connection:  # what an interrupted older run left behind
            connection.execute("UPDATE items SET status = 'planned' WHERE id = ?", (item["id"],))
        job = self.scan()
        self.assertEqual(store.get(item["id"]).status, ItemStatus.PUBLISHED)
        self.assertEqual(job["result"]["counts"]["executed"], 1)
        self.assertEqual(job["progress"]["done"], job["progress"]["total"])


if __name__ == "__main__":
    unittest.main()
