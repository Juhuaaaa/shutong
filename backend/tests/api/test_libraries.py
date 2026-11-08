import json
import shutil
import unittest

from ..engine.reader_ai import ReaderAi
from .helpers import ApiCase


class LibraryRoutesTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_create_list_and_update(self):
        library = self.make_library()
        self.assertEqual((library["name"], library["source_policy"], library["available"]), ("漫画", "keep", True))
        self.assertEqual([entry["id"] for entry in self.client.get("/api/libraries").json()], [library["id"]])
        changed = self.client.patch("/api/libraries/{0}".format(library["id"]),
                                    json={"naming_template": "{series}/{volume}{ext}", "pdf_to_cbz": False})
        self.assertEqual((changed.json()["naming_template"], changed.json()["pdf_to_cbz"]),
                         ("{series}/{volume}{ext}", False))

    def test_the_template_decides_the_edition(self):
        library = self.make_library()
        self.assertNotIn("include_edition", library)
        self.ai = ReaderAi(series={"迷宫饭[bili电子版]": {"title": "迷宫饭", "edition": "bili电子版"}})
        self.zip("迷宫饭[bili电子版]/迷宫饭 Vol.01.zip")
        self.client.post("/api/libraries/{0}/scan".format(library["id"]))
        [item] = self.client.get("/api/items", params={"library_id": library["id"]}).json()["items"]
        self.assertEqual((item["status"], item["plan"]["series"]), ("published", "迷宫饭"), item)
        self.assertEqual(item["target_path"], "迷宫饭/迷宫饭 Vol.01.cbz")
        template = "{series}{edition:[%s]}/{series}{edition:[%s]} {volume}{ext}"
        preview = self.client.post("/api/libraries/{0}/template-preview".format(library["id"]),
                                   json={"template": template}).json()
        self.assertEqual(preview["examples"][0]["target"], "迷宫饭[bili电子版]/迷宫饭[bili电子版] Vol.01.cbz")
        author = self.client.post("/api/libraries/{0}/template-preview".format(library["id"]),
                                  json={"template": "{author}/{series} {volume}{ext}"}).json()
        self.assertEqual(author["examples"][0]["target"], "未知作者/迷宫饭 Vol.01.cbz")
        # Plans written before {author}: the series named its edition, the writers are in the metadata.
        with self.app.state.db.connect() as connection:
            plan = json.loads(connection.execute("SELECT plan FROM items").fetchone()[0])
            plan["fields"] = {key: value for key, value in plan["fields"].items() if key != "author"}
            plan["fields"]["series"] = "迷宫饭[bili电子版]"
            plan["metadata"]["writers"] = ["九井谅子"]
            connection.execute("UPDATE items SET plan = ?", (json.dumps(plan),))
        old = self.client.post("/api/libraries/{0}/template-preview".format(library["id"]),
                               json={"template": "{author}/{series} {volume}{ext}"}).json()
        self.assertEqual(old["examples"][0]["target"], "九井谅子/迷宫饭 Vol.01.cbz")

    def test_overwrite_policy_and_rename_switch(self):
        library = self.make_library()
        self.assertEqual((library["overwrite_policy"], library["rename_files"]), ("never", True))
        changed = self.client.patch("/api/libraries/{0}".format(library["id"]),
                                    json={"overwrite_policy": "larger", "rename_files": False}).json()
        self.assertEqual((changed["overwrite_policy"], changed["rename_files"]), ("larger", False))
        self.assertEqual(self.client.patch("/api/libraries/{0}".format(library["id"]),
                                           json={"overwrite_policy": "maybe"}).status_code, 422)

    def test_bad_template_is_rejected_and_nothing_changes(self):
        library = self.make_library()
        bad = self.client.patch("/api/libraries/{0}".format(library["id"]), json={"naming_template": "{series}"})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("{ext}", bad.json()["detail"])
        self.assertEqual(self.client.get("/api/libraries/{0}".format(library["id"])).json()["naming_template"], "")
        created = self.client.post("/api/libraries", json={"name": "x", "kind": "manga", "source_dir": "/s",
                                                           "library_dir": "/l", "naming_template": "{nope}{ext}"})
        self.assertEqual(created.status_code, 422)

    def test_duplicate_name_and_archive_without_dir(self):
        self.make_library()
        again = self.client.post("/api/libraries", json={"name": "漫画", "kind": "manga", "source_dir": "/s",
                                                         "library_dir": "/l"})
        self.assertEqual((again.status_code, again.json()["detail"]), (409, "库名已存在"))
        archive = self.client.post("/api/libraries", json={"name": "小说", "kind": "novel", "source_dir": "/s",
                                                           "library_dir": "/l", "source_policy": "archive"})
        self.assertEqual((archive.status_code, archive.json()["detail"]), (422, "「移到原档目录」需要填写原档目录"))

    def test_unknown_library(self):
        missing = self.client.get("/api/libraries/99")
        self.assertEqual((missing.status_code, missing.json()["detail"]), (404, "库不存在"))

    def test_available_reflects_directories(self):
        library = self.make_library()
        shutil.rmtree(self.root / "source")
        self.assertFalse(self.client.get("/api/libraries/{0}".format(library["id"])).json()["available"])

    def test_scan_records_a_run_and_counts(self):
        library = self.make_library()
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("迷宫饭/迷宫饭 Vol.02.zip")
        job = self.client.post("/api/libraries/{0}/scan".format(library["id"])).json()
        self.assertEqual(self.client.get("/api/jobs/{0}".format(job["job_id"])).json()["state"], "done")
        runs = self.client.get("/api/libraries/{0}/runs".format(library["id"])).json()
        self.assertEqual((len(runs), runs[0]["trigger"], runs[0]["counts"].get("published")), (1, "manual", 2))
        summary = self.client.get("/api/libraries/{0}/summary".format(library["id"])).json()
        self.assertEqual(summary["counts"], {"published": 2})

    def test_scan_of_missing_directory_fails_the_job(self):
        library = self.make_library()
        shutil.rmtree(self.root / "source")
        job = self.client.post("/api/libraries/{0}/scan".format(library["id"])).json()
        result = self.client.get("/api/jobs/{0}".format(job["job_id"])).json()
        self.assertEqual(result["state"], "failed")
        self.assertTrue(result["error"].startswith("库目录不可用"))

    def test_series_directories(self):
        library = self.make_library()
        for name in ("迷宫饭", "婚戒物语[东立电子版]", ".shutong"):
            (self.root / "library" / name).mkdir()
        (self.root / "library" / "loose.cbz").write_bytes(b"x")
        series = self.client.get("/api/libraries/{0}/series".format(library["id"])).json()
        self.assertEqual(series, ["婚戒物语[东立电子版]", "迷宫饭"])
        shutil.rmtree(self.root / "library")
        self.assertEqual(self.client.get("/api/libraries/{0}/series".format(library["id"])).status_code, 409)

    def test_template_preview(self):
        library = self.make_library()
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.client.post("/api/libraries/{0}/scan".format(library["id"]))
        preview = self.client.post("/api/libraries/{0}/template-preview".format(library["id"]),
                                   json={"template": "{series}/{volume}{ext}"}).json()
        self.assertEqual(preview["examples"], [{"source": "迷宫饭 Vol.01.zip", "target": "迷宫饭/Vol.01.cbz"}])
        bad = self.client.post("/api/libraries/{0}/template-preview".format(library["id"]),
                               json={"template": "{series}"})
        self.assertEqual(bad.status_code, 422)


if __name__ == "__main__":
    unittest.main()
