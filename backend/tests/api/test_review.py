import unittest

from shutong.api.routes.review import adoptable_choices
from shutong.metadata.base import MetadataUnavailable

from ..engine.reader_ai import ReaderAi
from ..engine.test_match import FakeSource
from .helpers import ApiCase


class ReviewRoutesTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.ai = ReaderAi(unsure_series={"[]a", "[]b"})
        self.login()
        self.library = self.make_library()
        self.zip("[]a/Vol.01.zip")
        self.zip("[]b/Vol.01.zip")
        self.zip("[]b/Vol.02.zip")
        self.client.post("/api/libraries/{0}/scan".format(self.library["id"]))

    def groups(self):
        return self.client.get("/api/review/groups", params={"library_id": self.library["id"]}).json()

    def test_adopt_the_ai_suggestions_of_many_groups_at_once(self):
        groups = self.groups()
        self.assertEqual([group["adoptable"] for group in groups], [True, True])
        ids = [item_id for group in groups for item_id in group["item_ids"]]
        response = self.client.post("/api/review/adopt", json={"item_ids": ids})
        job = self.client.get("/api/jobs/{0}".format(response.json()["job_id"])).json()
        self.assertEqual((job["kind"], job["state"]), ("adopt", "done"), job)
        self.assertEqual((job["result"]["groups"], job["result"]["executed"]), (2, 3))
        self.assertEqual(self.groups(), [])
        self.assertEqual(self.client.post("/api/review/adopt", json={"item_ids": []}).status_code, 422)

    def test_groups_by_source_folder(self):
        groups = self.groups()
        self.assertEqual([(group["folder"], group["count"]) for group in groups], [("[]b", 2), ("[]a", 1)])
        self.assertEqual(groups[0]["reasons"], ["naming"])
        self.assertEqual(sorted(groups[0]["sample_names"]), ["Vol.01.zip", "Vol.02.zip"])
        self.assertEqual((groups[0]["ai_suggestion"]["title"], groups[0]["ai_suggestion"]["confidence"]), ("[]b", 0.3))
        self.assertNotIn("edition_signals", groups[0])

    def test_confirm_one_group(self):
        group = self.groups()[0]
        response = self.client.post("/api/review/confirm",
                                    json={"item_ids": group["item_ids"], "title": "迷宫饭",
                                          "subject": {"source": "bangumi", "id": 133315}})
        job = self.client.get("/api/jobs/{0}".format(response.json()["job_id"])).json()
        self.assertEqual((job["state"], job["result"]["replanned"], job["result"]["executed"]), ("done", 2, 2))
        self.assertEqual([group["folder"] for group in self.groups()], ["[]a"])

    def test_reidentify_a_library_or_some_items(self):
        response = self.client.post("/api/review/reidentify", json={"library_id": self.library["id"]})
        job = self.client.get("/api/jobs/{0}".format(response.json()["job_id"])).json()
        self.assertEqual((job["kind"], job["state"]), ("reidentify", "done"))
        self.assertEqual(job["result"], {"needs_review": 3, "skipped": 0})
        self.ai = ReaderAi(series={"[]b": {"title": "迷宫饭", "confidence": 0.97}})  # the AI knows []b now
        group = self.groups()[0]
        response = self.client.post("/api/review/reidentify", json={"item_ids": group["item_ids"]})
        job = self.client.get("/api/jobs/{0}".format(response.json()["job_id"])).json()
        self.assertEqual((job["result"]["executed"], job["result"]["skipped"]), (2, 0))
        self.assertEqual([group["folder"] for group in self.groups()], ["[]a"])
        self.assertEqual(self.client.post("/api/review/reidentify", json={}).status_code, 422)

    def test_skip_metadata_publishes_under_the_title(self):
        group = self.groups()[0]
        missing = self.client.post("/api/review/confirm", json={"item_ids": group["item_ids"], "volumes": {},
                                                                "subject": {"source": "bangumi", "id": "133315"},
                                                                "skip_metadata": True})
        self.assertEqual((missing.status_code, missing.json()["detail"]), (422, "直接整理要先填书名"))
        response = self.client.post("/api/review/confirm",
                                    json={"item_ids": group["item_ids"], "title": "天鹅绒之吻", "skip_metadata": True})
        job = self.client.get("/api/jobs/{0}".format(response.json()["job_id"])).json()
        self.assertEqual((job["state"], job["result"]["executed"]), ("done", 2))
        self.assertTrue((self.root / "library" / "天鹅绒之吻" / "天鹅绒之吻 Vol.02.cbz").exists())

    def test_empty_confirmation_rejected(self):
        group = self.groups()[0]
        response = self.client.post("/api/review/confirm", json={"item_ids": group["item_ids"]})
        self.assertEqual((response.status_code, response.json()["detail"]),
                         (422, "至少要指定系列名、条目或卷号"))

    def test_bad_volume_rejected(self):
        group = self.groups()[1]
        response = self.client.post("/api/review/confirm",
                                    json={"item_ids": group["item_ids"],
                                          "volumes": {str(group["item_ids"][0]): "第一卷"}})
        self.assertEqual(response.status_code, 422)
        self.assertIn("无法识别的卷号", response.json()["detail"])

    def test_bad_title_rejected_in_chinese(self):
        group = self.groups()[0]
        response = self.client.post("/api/review/confirm", json={"item_ids": group["item_ids"], "title": " x"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("系列名", response.json()["detail"])

    def test_ask_ai_endpoint_is_gone(self):
        group = self.groups()[0]
        self.assertEqual(self.client.post("/api/review/ai", json={"item_ids": group["item_ids"]}).status_code, 404)

    def test_metadata_search(self):
        results = self.client.get("/api/metadata/search", params={"q": "迷宫饭"}).json()
        self.assertEqual([(entry["subject_id"], entry["source"], entry["name_cn"]) for entry in results],
                         [("133315", "bangumi", "迷宫饭")])
        self.assertEqual(results[0]["web_url"], "https://bgm.tv/subject/133315")
        self.assertIn("/v0/subjects/133315/image", results[0]["image"])
        subject = self.client.get("/api/metadata/subjects/bangumi/133315").json()
        self.assertEqual(subject["name_cn"], "迷宫饭")

    def test_metadata_unavailable(self):
        self.source = FakeSource(error=MetadataUnavailable("timeout"))
        response = self.client.get("/api/metadata/search", params={"q": "迷宫饭"})
        self.assertEqual((response.status_code, response.json()["detail"]), (503, "Bangumi 暂时无法访问"))



class AdoptableTests(unittest.TestCase):
    def group(self, reasons, suggestion, candidates=()):
        return {"reasons": reasons, "ai_suggestion": suggestion, "candidates": list(candidates)}

    def test_what_a_suggestion_can_settle(self):
        naming = {"title": "迷宫饭", "edition": "bili电子版", "subject_id": None, "problem": None}
        self.assertEqual(adoptable_choices(self.group(["naming"], naming)), {"title": "迷宫饭", "edition": "bili电子版"})
        pick = {"title": None, "edition": None, "subject_id": "30002", "source": "anilist", "problem": None}
        self.assertEqual(adoptable_choices(self.group(["metadata"], pick))["subject"].key, "anilist:30002")
        old = dict(pick, source=None, subject_id=9)
        self.assertEqual(adoptable_choices(self.group(["metadata"], old, [{"source": "bangumi", "id": "9"}]))["subject"].key,
                         "bangumi:9")

    def test_what_it_cannot(self):
        naming = {"title": "迷宫饭", "edition": None, "subject_id": None, "problem": None}
        self.assertIsNone(adoptable_choices(self.group(["volume"], naming)))
        self.assertIsNone(adoptable_choices(self.group(["naming", "conflict"], naming)))
        self.assertIsNone(adoptable_choices(self.group(["metadata"], naming)))  # no entry picked
        self.assertIsNone(adoptable_choices(self.group(["naming"], dict(naming, problem="AI 调用失败"))))
        self.assertIsNone(adoptable_choices(self.group(["naming"], None)))


if __name__ == "__main__":
    unittest.main()
