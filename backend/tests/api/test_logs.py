import unittest

from .helpers import ApiCase


class LogRoutesTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_needs_login(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/logs").status_code, 401)

    def test_scan_is_logged_and_filtered(self):
        library = self.make_library()
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("[]/Vol.01.zip")
        self.client.post("/api/libraries/{0}/scan".format(library["id"]))
        body = self.client.get("/api/logs").json()
        messages = "\\n".join(entry["message"] for entry in body["entries"])
        self.assertIn("开始任务：扫描", messages)
        self.assertIn("任务完成：扫描", messages)
        self.assertNotIn("进入复核", messages)  # per-item review lines are DEBUG: a big scan would flood the page
        self.assertIn("入库 1", messages)
        self.assertIn("已整理：迷宫饭 Vol.01.zip", messages)
        self.assertIn("复核 1", messages)
        self.assertNotIn("run_id", messages)
        later = self.client.get("/api/logs", params={"after": body["last_seq"]}).json()
        self.assertEqual(later["entries"], [])
        only = self.client.get("/api/logs", params={"q": "复核"}).json()["entries"]
        self.assertTrue(only and all("复核" in entry["message"] for entry in only))
        warnings = self.client.get("/api/logs", params={"level": "WARNING"}).json()["entries"]
        self.assertTrue(all(entry["level"] in ("WARNING", "ERROR") for entry in warnings))
        self.client.patch("/api/settings", json={"log.level": "DEBUG"})
        self.client.post("/api/libraries/{0}/scan".format(library["id"]))
        self.client.post("/api/review/reidentify", json={"library_id": library["id"]})
        detailed = "\n".join(entry["message"] for entry in self.client.get("/api/logs").json()["entries"])
        self.client.patch("/api/settings", json={"log.level": "INFO"})
        self.assertIn("进入复核（命名不确定）：Vol.01.zip：AI 对书名没有把握", detailed)

    def test_failed_job_logs_the_traceback(self):
        def boom():
            raise RuntimeError("坏掉的任务")
        self.app.state.jobs.submit("scan", boom)
        errors = self.client.get("/api/logs", params={"level": "ERROR"}).json()["entries"]
        self.assertTrue(any("坏掉的任务" in entry["message"] and "Traceback" in entry["message"] for entry in errors))

    def test_download_and_level_setting(self):
        self.assertEqual(self.client.patch("/api/settings", json={"log.level": "TRACE"}).status_code, 422)
        self.assertEqual(self.client.patch("/api/settings", json={"log.level": "DEBUG"}).status_code, 200)
        import logging
        self.assertEqual(logging.getLogger("shutong").level, logging.DEBUG)
        self.client.patch("/api/settings", json={"log.level": "INFO"})
        download = self.client.get("/api/logs/download")
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download.headers["content-disposition"])
        self.assertIn("书童启动", download.text)


if __name__ == "__main__":
    unittest.main()
