"""A library without a source dir: files only come in through the upload page."""
import unittest

from .helpers import ApiCase
from .test_upload import archive


class UploadOnlyLibraryTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_empty_source_keeps_uploads_inside_the_data_dir_and_deletes_them_once_organized(self):
        library = self.make_library(source_dir="", source_policy="delete")
        self.assertEqual((library["source_dir"], library["available"], library["watch"]), ("", True, False))
        response = self.client.post("/api/libraries/{0}/upload".format(library["id"]),
                                    files=[("files", ("迷宫饭/迷宫饭 Vol.01.zip", archive("1"), "application/zip"))])
        self.assertEqual(response.status_code, 200, response.text)
        uploads = self.data_dir / "uploads" / str(library["id"])
        self.assertTrue((uploads / "迷宫饭" / "迷宫饭 Vol.01.zip").exists())
        job = self.client.post("/api/libraries/{0}/scan".format(library["id"])).json()
        self.assertEqual(self.client.get("/api/jobs/{0}".format(job["job_id"])).json()["state"], "done")
        self.assertTrue((self.root / "library" / "迷宫饭" / "迷宫饭 Vol.01.cbz").exists())
        self.assertFalse((uploads / "迷宫饭" / "迷宫饭 Vol.01.zip").exists())

    def test_empty_source_cannot_keep_originals_or_be_watched(self):
        response = self.client.post("/api/libraries", json={"name": "漫画", "kind": "manga", "source_dir": "",
                                                            "library_dir": str(self.root)})
        self.assertEqual((response.status_code, response.json()["detail"]),
                         (422, "来源目录留空时，整理后只能删除原文件或移到原档目录"))
        response = self.client.post("/api/libraries", json={"name": "漫画", "kind": "manga", "source_dir": "",
                                                            "library_dir": str(self.root), "source_policy": "delete",
                                                            "watch": True})
        self.assertEqual((response.status_code, response.json()["detail"]), (422, "来源目录留空时不能开目录监控"))

    def test_clearing_the_source_of_an_existing_library(self):
        library = self.make_library()
        response = self.client.patch("/api/libraries/{0}".format(library["id"]),
                                     json={"source_dir": "", "source_policy": "delete"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["source_dir"], "")
        response = self.client.patch("/api/libraries/{0}".format(library["id"]), json={"source_policy": "keep"})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
