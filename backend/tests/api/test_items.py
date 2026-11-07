import io
import unittest
import zipfile

from PIL import Image

from shutong.engine.kinds.manga.comicinfo import read_comic_info

from ..engine.test_match import subject
from .helpers import ApiCase


def jpeg(image):
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def page(colour):
    return jpeg(Image.new("RGB", (272, 400), colour))


class ItemRoutesTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.login()
        self.library = self.make_library()
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("迷宫饭/迷宫饭 Vol.02.zip")
        self.client.post("/api/libraries/{0}/scan".format(self.library["id"]))

    def items(self, **params):
        params.setdefault("library_id", self.library["id"])
        return self.client.get("/api/items", params=params).json()

    def job(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        return self.client.get("/api/jobs/{0}".format(response.json()["job_id"])).json()

    def test_list_pages_filters_and_search(self):
        page = self.items(limit=1)
        self.assertEqual((len(page["items"]), page["total"]), (1, 2))
        self.assertEqual(self.items(status="published")["total"], 2)
        self.assertEqual(self.items(status="planned")["total"], 0)
        found = self.items(q="vol.02")
        self.assertEqual([item["source_name"] for item in found["items"]], ["迷宫饭 Vol.02.zip"])
        self.assertEqual(self.client.get("/api/items", params={"status": "nope"}).status_code, 422)

    def test_detail_has_events(self):
        item = self.items()["items"][0]
        detail = self.client.get("/api/items/{0}".format(item["id"])).json()
        kinds = [event["kind"] for event in detail["events"]]
        self.assertEqual(kinds[:4], ["discovered", "parsed", "matched", "planned"])
        self.assertIn("published", kinds)
        self.assertEqual(detail["ai_calls"], [])
        missing = self.client.get("/api/items/999")
        self.assertEqual((missing.status_code, missing.json()["detail"]), (404, "条目不存在"))

    def test_reorganize_deletes_the_old_output_and_publishes_again(self):
        item = min(self.items()["items"], key=lambda item: item["id"])
        old = self.root / "library" / item["target_path"]
        job = self.job(self.client.post("/api/items/reorganize",
                                        json={"item_ids": [item["id"]], "title": "迷宫饭 新", "bgm": 133315}))
        self.assertEqual((job["state"], job["result"]["deleted"], job["result"]["executed"]), ("done", 1, 1))
        self.assertFalse(old.exists())
        self.assertFalse((self.root / "library" / ".shutong" / "trash").exists())
        detail = self.client.get("/api/items/{0}".format(item["id"])).json()
        self.assertEqual((detail["status"], detail["target_path"]), ("published", "迷宫饭 新/迷宫饭 新 Vol.01.cbz"))
        self.assertTrue((self.root / "library" / detail["target_path"]).exists())

    def test_reorganize_rejects_bad_choices_up_front(self):
        item = self.items()["items"][0]
        for body in ({"title": "Fate/Zero"}, {"volumes": {str(item["id"]): "abc"}}):
            with self.subTest(body=body):
                response = self.client.post("/api/items/reorganize", json=dict(body, item_ids=[item["id"]]))
                self.assertEqual(response.status_code, 422)
                self.assertRegex(response.json()["detail"], "系列名|卷号")

    def map_library(self):
        server = self.make_server()
        self.client.patch("/api/libraries/{0}".format(self.library["id"]),
                          json={"server_id": server["id"], "server_library_id": 3})

    def test_scan_notifies_kavita_once(self):
        self.map_library()
        self.zip("迷宫饭/迷宫饭 Vol.03.zip")
        self.zip("迷宫饭/迷宫饭 Vol.04.zip")
        job = self.job(self.client.post("/api/libraries/{0}/scan".format(self.library["id"])))
        self.assertEqual((job["result"]["counts"]["executed"], job["result"]["counts"]["kavita"]["scanned"]),
                         (2, [{"server": "家里", "library_id": "3"}]))
        self.assertEqual(self.server_calls(), [("scan", "3")])

    def test_already_published_items_do_not_trigger_a_scan(self):
        item = self.items()["items"][0]
        self.map_library()
        job = self.job(self.client.post("/api/items/execute", json={"item_ids": [item["id"]]}))
        self.assertEqual((job["result"]["skipped"], job["result"]["kavita"]["scanned"]), (1, []))
        self.assertEqual(self.server_calls(), [])

    def test_kavita_failure_keeps_the_job_done(self):
        self.map_library()
        self.server_error = "Kavita 用户名或密码错误"
        self.zip("迷宫饭/迷宫饭 Vol.03.zip")
        job = self.job(self.client.post("/api/libraries/{0}/scan".format(self.library["id"])))
        self.assertEqual((job["state"], job["result"]["counts"]["kavita"]["errors"]),
                         ("done", ["家里：Kavita 用户名或密码错误"]))
        self.assertEqual(self.items(status="published")["total"], 3)

    def test_reorganized_series_gets_its_covers_refreshed(self):
        self.map_library()
        item = min(self.items()["items"], key=lambda item: item["id"])
        job = self.job(self.client.post("/api/items/reorganize", json={"item_ids": [item["id"]]}))
        self.assertEqual(job["result"]["kavita"]["refreshed"], ["迷宫饭"])

    def edit(self, body):
        return self.job(self.client.post("/api/items/metadata", json=body))

    def test_manual_metadata_is_written_into_the_file_without_repacking(self):
        item = min(self.items()["items"], key=lambda item: item["id"])
        path = self.root / "library" / item["target_path"]
        with self.app.state.db.connect() as connection:
            connection.execute("UPDATE items SET subject_id = NULL WHERE id = ?", (item["id"],))
        job = self.edit({"item_ids": [item["id"]], "fields": {"writers": ["九井谅子"], "summary": "迷宫里做饭",
                                                                  "release_date": "2014-02", "genres": "美食，奇幻"}})
        self.assertEqual((job["state"], job["result"]["edited"]), ("done", 1), job)
        info = read_comic_info(path)
        self.assertEqual((info["Writer"], info["Summary"], info["Year"], info["Month"], info["Genre"]),
                         ("九井谅子", "迷宫里做饭", "2014", "2", "美食, 奇幻"))
        self.assertNotIn("Day", info)
        detail = self.client.get("/api/items/{0}".format(item["id"])).json()
        self.assertEqual(detail["overrides"]["metadata"]["writers"], ["九井谅子"])
        self.assertEqual(detail["events"][-1]["kind"], "metadata_edited")
        groups = self.client.get("/api/history/groups", params={"missing_metadata": "true"}).json()
        self.assertEqual(groups["total"], 0)  # filled in by hand counts as having metadata

    def test_picking_a_subject_rewrites_the_files_with_it(self):
        self.source.subjects[302561] = subject(302561, "我独自升级", total=14)
        ids = [item["id"] for item in self.items()["items"]]
        job = self.edit({"item_ids": ids, "bgm": 302561})
        self.assertEqual(job["result"]["edited"], 2, job)
        for item_id in ids:
            detail = self.client.get("/api/items/{0}".format(item_id)).json()
            self.assertEqual((detail["subject_id"], detail["overrides"]["subject"]), ("302561", {"source": "bangumi", "id": "302561"}))
            info = read_comic_info(self.root / "library" / detail["target_path"])
            self.assertEqual((info["Web"], info["LocalizedSeries"], info["Series"]),
                             ("https://bgm.tv/subject/302561", "我独自升级", "迷宫饭"))

    def test_an_edit_tells_kavita_to_refresh_the_series(self):
        self.map_library()
        item = self.items()["items"][0]
        job = self.edit({"item_ids": [item["id"]], "fields": {"summary": "迷宫里做饭"}})
        self.assertEqual(job["result"]["kavita"]["refreshed"], ["迷宫饭"])
        self.assertEqual(self.server_calls()[0], ("scan", "3"))

    def test_reorganizing_keeps_what_was_filled_in_by_hand(self):
        item = min(self.items()["items"], key=lambda item: item["id"])
        self.edit({"item_ids": [item["id"]], "fields": {"writers": ["九井谅子"]}})
        job = self.job(self.client.post("/api/items/reorganize", json={"item_ids": [item["id"]]}))
        self.assertEqual(job["result"]["executed"], 1, job)
        detail = self.client.get("/api/items/{0}".format(item["id"])).json()
        self.assertEqual(read_comic_info(self.root / "library" / detail["target_path"])["Writer"], "九井谅子")

    def test_refresh_metadata_of_some_files_or_a_whole_library(self):
        items = self.items()["items"]
        def refresh(body):
            response = self.client.post("/api/items/refresh-metadata", json=body)
            self.assertEqual(response.status_code, 200, response.text)
            return self.job(response)
        job = refresh({"item_ids": [items[0]["id"]]})
        self.assertEqual(job["state"], "done", job)
        job = refresh({"library_id": self.library["id"]})
        self.assertEqual(job["result"]["skipped"] + job["result"]["unchanged"], len(items), job)
        self.assertEqual(self.client.post("/api/items/refresh-metadata", json={}).status_code, 422)

    def published_cbz(self):
        item = min(self.items()["items"], key=lambda item: item["id"])
        path = self.root / "library" / item["target_path"]
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("001.jpg", page((10, 10, 10)))
            archive.writestr("002.jpg", page((200, 200, 200)))
            archive.writestr("ComicInfo.xml", "<ComicInfo><Series>迷宫饭</Series><PageCount>2</PageCount></ComicInfo>")
        return item, path

    def test_a_file_lists_its_pages_and_serves_thumbnails(self):
        item, _ = self.published_cbz()
        options = self.client.get("/api/items/{0}/cover-options".format(item["id"])).json()
        self.assertEqual((options["pages"], options["current"], options["added"]), (["001.jpg", "002.jpg"], "001.jpg", False))
        image = self.client.get("/api/items/{0}/cover-image".format(item["id"]), params={"w": 100})
        self.assertEqual((image.status_code, image.headers["content-type"]), (200, "image/jpeg"))
        self.assertEqual(self.client.get("/api/items/{0}/cover-image".format(item["id"]), params={"page": "../x"}).status_code, 404)
        self.assertEqual(self.client.get("/api/items/999999/cover-image").status_code, 404)

    def test_choosing_a_cover_writes_it_and_remembers_it(self):
        item, path = self.published_cbz()
        job = self.job(self.client.post("/api/items/{0}/cover".format(item["id"]), json={"page": "002.jpg"}))
        self.assertEqual(job["state"], "done", job)
        with zipfile.ZipFile(path) as archive:
            self.assertIn("000.jpg", archive.namelist())
        detail = self.client.get("/api/items/{0}".format(item["id"])).json()
        self.assertEqual(detail["overrides"]["cover"]["page"], "002.jpg")
        self.assertEqual(detail["events"][-1]["kind"], "cover_set")
        job = self.job(self.client.post("/api/items/{0}/cover".format(item["id"]), json={"page": "001.jpg"}))
        self.assertNotIn("cover", self.client.get("/api/items/{0}".format(item["id"])).json()["overrides"])

    def test_a_cover_is_refused_when_the_choice_makes_no_sense(self):
        item, _ = self.published_cbz()
        url = "/api/items/{0}/cover".format(item["id"])
        self.assertEqual(self.client.post(url, json={"page": "nope.jpg"}).status_code, 422)
        self.assertEqual(self.client.post(url, json={"page": "001.jpg", "left": 0.9, "right": 0.1}).status_code, 422)
        self.assertEqual(self.client.post("/api/items/999999/cover", json={"page": "x"}).status_code, 404)

    def test_a_novel_has_no_cover_to_change(self):
        novels = self.client.post("/api/libraries", json={"name": "轻小说", "kind": "novel", "source_dir": str(self.root / "source"),
                                                          "library_dir": str(self.root / "library")}).json()
        item = min(self.items()["items"], key=lambda entry: entry["id"])
        with self.app.state.db.connect() as connection:
            connection.execute("UPDATE items SET library_id = ? WHERE id = ?", (novels["id"], item["id"]))
        for response in (self.client.get("/api/items/{0}/cover-options".format(item["id"])),
                         self.client.get("/api/items/{0}/cover-image".format(item["id"])),
                         self.client.post("/api/items/{0}/cover".format(item["id"]), json={"page": "001.jpg"})):
            self.assertEqual(response.status_code, 409)
            self.assertIn("只有漫画", response.json()["detail"])

    def test_jackets_of_a_folder_are_cropped_and_ordinary_volumes_left_alone(self):
        item, path = self.published_cbz()
        wide = Image.new("RGB", (800, 400), (200, 200, 200))
        wide.paste((220, 40, 40), (120, 0, 392, 400))
        wide.paste((20, 20, 120), (392, 0, 424, 400))
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("001.jpg", jpeg(wide))
            archive.writestr("002.jpg", page((1, 1, 1)))
            archive.writestr("ComicInfo.xml", "<ComicInfo><Series>迷宫饭</Series><PageCount>2</PageCount></ComicInfo>")
        ids = [entry["id"] for entry in self.items()["items"]]
        job = self.job(self.client.post("/api/items/crop-jackets", json={"item_ids": ids}))
        self.assertEqual((job["result"]["cropped"], job["result"]["skipped"], job["result"]["failed"]), (1, 1, 0), job)
        with zipfile.ZipFile(path) as archive:
            self.assertIn("000.jpg", archive.namelist())
        again = self.job(self.client.post("/api/items/crop-jackets", json={"item_ids": ids}))
        self.assertEqual(again["result"]["cropped"], 0)

    def test_metadata_edit_checks_its_input_and_skips_what_is_not_organized(self):
        item = self.items()["items"][0]
        for body, message in (({}, "Bangumi 条目或手填"), ({"bgm": 1, "fields": {"summary": "x"}}, "Bangumi 条目或手填"),
                              ({"fields": {"release_date": "明年"}}, "发售日期"), ({"fields": {}}, "至少填一项")):
            with self.subTest(body=body):
                response = self.client.post("/api/items/metadata", json=dict(body, item_ids=[item["id"]]))
                self.assertEqual(response.status_code, 422)
                self.assertIn(message, response.json()["detail"])
        self.client.post("/api/items/cancel", json={"item_ids": [item["id"]]})
        (self.root / "library" / item["target_path"]).unlink()
        job = self.edit({"item_ids": [item["id"]], "fields": {"summary": "x"}})
        self.assertEqual((job["result"]["edited"], job["result"]["failed"]), (0, 1))
        detail = self.client.get("/api/items/{0}".format(item["id"])).json()
        self.assertEqual(detail["events"][-1]["kind"], "metadata_edit_failed")

    def test_cancel_and_empty_selection(self):
        item = self.items()["items"][0]
        response = self.client.post("/api/items/cancel", json={"item_ids": [item["id"]]})
        self.assertEqual(response.json(), {"cancelled": 0, "skipped": 1})  # published items stay
        empty = self.client.post("/api/items/execute", json={"item_ids": []})
        self.assertEqual((empty.status_code, empty.json()["detail"]), (422, "没有选择条目"))
        gone = self.client.post("/api/items/execute-planned", json={"library_id": self.library["id"]})
        self.assertIn(gone.status_code, (404, 405))

    def test_retry(self):
        item = self.items()["items"][0]
        job = self.job(self.client.post("/api/items/retry", json={"item_ids": [item["id"]]}))
        self.assertEqual((job["state"], job["result"]["skipped"]), ("done", 1))


if __name__ == "__main__":
    unittest.main()
