"""After a drop: what may be offered for the trash, and what is left of a folder afterwards."""
from .test_desktop import DesktopCase


class OriginalsTests(DesktopCase):
    def setUp(self):
        super().setUp()
        self.lib = self.library()
        self.downloads = self.root / "下载"

    def drop(self, relative="迷宫饭/迷宫饭 Vol.01.zip", path=None):
        source = self.zip(relative, base=self.downloads)
        response = self.window.post("/api/libraries/{0}/scan-paths".format(self.lib["id"]),
                                    json={"paths": [str(path or source.parent)]})
        self.assertEqual(response.status_code, 200, response.text)
        return source

    def offered(self):
        return self.window.get("/api/desktop/originals").json()["items"]

    def trashed(self, *ids):
        response = self.window.post("/api/desktop/originals/trashed", json={"ids": list(ids)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["empty_dirs"]

    def test_lists_published_originals(self):
        source = self.drop()
        items = self.offered()
        self.assertEqual([(item["path"], item["name"], item["library_id"]) for item in items],
                         [(str(source), source.name, self.lib["id"])])

    def test_review_item_is_not_offered(self):
        self.drop("[]看不懂/x Vol.01.zip")
        self.assertEqual(self.offered(), [])

    def test_failed_item_is_not_offered(self):
        source = self.zip("迷宫饭/迷宫饭 Vol.01.zip", base=self.downloads)
        source.write_bytes(b"not an archive")
        self.window.post("/api/libraries/{0}/scan-paths".format(self.lib["id"]), json={"paths": [str(source.parent)]})
        self.assertEqual(self.offered(), [])

    def test_changed_original_is_not_offered(self):
        source = self.drop()
        source.write_bytes(b"something else entirely")
        self.assertEqual(self.offered(), [])

    def test_moved_original_is_not_offered(self):
        source = self.drop()
        source.unlink()
        self.assertEqual(self.offered(), [])

    def test_original_is_not_offered_once_the_library_copy_is_gone(self):
        self.drop()
        for path in (self.root / "库").rglob("*.cbz"):
            path.unlink()
        self.assertEqual(self.offered(), [])

    def test_keep_hides_it_for_good(self):
        self.drop()
        ids = [item["id"] for item in self.offered()]
        self.assertEqual(self.window.post("/api/desktop/originals/keep", json={"ids": ids}).status_code, 200)
        self.assertEqual(self.offered(), [])

    def test_trashed_records_the_event(self):
        source = self.drop()
        item = self.offered()[0]
        source.unlink()
        self.trashed(item["id"])
        events = self.window.get("/api/items/{0}".format(item["id"])).json()["events"]
        self.assertEqual([event["detail"]["outcome"] for event in events if event["kind"] == "source_disposed"][-1], "trashed")

    def test_a_file_still_there_is_not_recorded_as_trashed(self):
        self.drop()
        item = self.offered()[0]
        self.trashed(item["id"])
        self.assertEqual(len(self.offered()), 1)
        events = self.window.get("/api/items/{0}".format(item["id"])).json()["events"]
        self.assertNotIn("trashed", [event["detail"].get("outcome") for event in events if event["detail"]])

    def test_folder_with_only_junk_left_is_returned(self):
        source = self.drop()
        (source.parent / ".DS_Store").write_bytes(b"x")
        (source.parent / "Thumbs.db").write_bytes(b"x")
        item = self.offered()[0]
        source.unlink()
        self.assertEqual(self.trashed(item["id"]), [str(source.parent)])

    def test_folder_with_other_files_stays(self):
        source = self.drop()
        (source.parent / "笔记.txt").write_text("留着")
        item = self.offered()[0]
        source.unlink()
        self.assertEqual(self.trashed(item["id"]), [])


    def test_a_loose_file_leaves_its_folder_alone(self):
        source = self.zip("迷宫饭 Vol.01.zip", base=self.downloads)
        self.window.post("/api/libraries/{0}/scan-paths".format(self.lib["id"]), json={"paths": [str(source)]})
        item = self.offered()[0]
        source.unlink()
        self.assertEqual(self.trashed(item["id"]), [])
        self.assertTrue(self.downloads.is_dir())

    def test_nested_empty_folders_come_back_as_the_outermost(self):
        source = self.zip("合集/甲/迷宫饭 Vol.01.zip", base=self.downloads)
        self.window.post("/api/libraries/{0}/scan-paths".format(self.lib["id"]), json={"paths": [str(self.downloads / "合集")]})
        item = self.offered()[0]
        source.unlink()
        self.assertEqual(self.trashed(item["id"]), [str(self.downloads / "合集" / "甲")])

    def test_web_mode_has_none_of_this(self):
        self.login()
        for method, path in (("get", "originals"), ("post", "originals/keep"), ("post", "originals/trashed")):
            response = getattr(self.client, method)("/api/desktop/" + path, **({"json": {"ids": []}} if method == "post" else {}))
            self.assertEqual(response.status_code, 404, path)
