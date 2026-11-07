"""Metadata sources over the API: listing, searching one source, and choosing a subject by {source, id}."""
from dataclasses import replace
import json

from shutong.metadata.base import MetadataUnavailable
from shutong.metadata.registry import SourceRegistry
from shutong.services import Services

from ..engine.reader_ai import ReaderAi
from ..engine.test_match import FakeSource, subject
from .helpers import DUNGEON, ApiCase

ANI_DUNGEON = replace(subject(30002, "", total=14, name="ダンジョン飯"), source="anilist",
                      aliases=("Delicious in Dungeon",), image="https://img/anilist.jpg")


class Named(FakeSource):
    def __init__(self, name, label, results=(), subjects=None, error=None):
        super().__init__(results, subjects, error)
        self.name, self.label = name, label


class MetadataSourcesApiTests(ApiCase):
    def setUp(self):
        self.bangumi = Named("bangumi", "Bangumi", [DUNGEON], {133315: DUNGEON})
        self.anilist = Named("anilist", "AniList", [ANI_DUNGEON], {30002: ANI_DUNGEON})
        self.enabled = ["bangumi"]
        super().setUp()
        self.login()

    def services(self, db):
        registry = SourceRegistry({"bangumi": self.bangumi, "anilist": self.anilist}, self.enabled)
        return Services(db, registry, self.ai, self.config)

    def test_sources_endpoint_order(self):
        self.enabled = ["anilist", "bangumi"]
        self.assertEqual(self.client.get("/api/metadata/sources").json(), [
            {"name": "anilist", "label": "AniList", "enabled": True},
            {"name": "bangumi", "label": "Bangumi", "enabled": True}])
        self.enabled = ["bangumi"]
        self.assertEqual(self.client.get("/api/metadata/sources").json(), [
            {"name": "bangumi", "label": "Bangumi", "enabled": True},
            {"name": "anilist", "label": "AniList", "enabled": False}])

    def test_search_with_source_param(self):
        results = self.client.get("/api/metadata/search", params={"q": "ダンジョン飯", "source": "anilist"}).json()
        self.assertEqual([(entry["subject_id"], entry["source"]) for entry in results], [("30002", "anilist")])
        self.assertEqual(results[0]["web_url"], "https://anilist.co/manga/30002")
        self.assertEqual(results[0]["image"], "https://img/anilist.jpg")
        self.assertEqual(results[0]["aliases"], ["Delicious in Dungeon"])
        self.assertEqual(self.anilist.searches, [("ダンジョン飯", "manga")])
        default = self.client.get("/api/metadata/search", params={"q": "迷宫饭"}).json()
        self.assertEqual(default[0]["source"], "bangumi")

    def test_search_unknown_source_422(self):
        response = self.client.get("/api/metadata/search", params={"q": "x", "source": "douban"})
        self.assertEqual(response.status_code, 422)

    def test_unavailable_names_the_source(self):
        self.anilist.error = MetadataUnavailable("timeout")
        response = self.client.get("/api/metadata/search", params={"q": "x", "source": "anilist"})
        self.assertEqual((response.status_code, response.json()["detail"]), (503, "AniList 暂时无法访问"))

    def test_subject_by_source_and_id(self):
        found = self.client.get("/api/metadata/subjects/anilist/30002").json()
        self.assertEqual((found["subject_id"], found["source"], found["name"]), ("30002", "anilist", "ダンジョン飯"))
        self.assertEqual(self.client.get("/api/metadata/subjects/douban/1").status_code, 422)
        self.assertEqual(self.client.get("/api/metadata/subjects/anilist/404").status_code, 404)

    def scan_into_review(self):
        self.ai = ReaderAi(unsure_series={"迷宫饭"})
        library = self.make_library()
        self.zip("迷宫饭/Vol.01.zip")
        self.client.post("/api/libraries/{0}/scan".format(library["id"]))
        [group] = self.client.get("/api/review/groups", params={"library_id": library["id"]}).json()
        return library, group

    def test_confirm_with_subject_ref(self):
        library, group = self.scan_into_review()
        response = self.client.post("/api/review/confirm", json={
            "item_ids": group["item_ids"], "title": "迷宫饭", "subject": {"source": "anilist", "id": 30002}})
        self.assertEqual(response.status_code, 200, response.text)
        item = self.client.get("/api/items/{0}".format(group["item_ids"][0])).json()
        self.assertEqual((item["subject_id"], item["subject_source"]), ("30002", "anilist"))
        bad = self.client.post("/api/review/confirm", json={
            "item_ids": group["item_ids"], "subject": {"source": "douban", "id": "1"}})
        self.assertEqual(bad.status_code, 422)
        blank = self.client.post("/api/review/confirm", json={
            "item_ids": group["item_ids"], "subject": {"source": "anilist", "id": ""}})
        self.assertEqual(blank.status_code, 422)

    def test_review_legacy_int_candidates(self):
        library, group = self.scan_into_review()
        with self.app.state.db.connect() as connection:
            connection.execute("UPDATE item_events SET detail = ? WHERE kind = 'review'",
                               (json.dumps({"note": "x", "candidates": [12, 34]}),))
        [group] = self.client.get("/api/review/groups", params={"library_id": library["id"]}).json()
        self.assertEqual(group["candidates"], [{"source": "bangumi", "id": "12"}, {"source": "bangumi", "id": "34"}])

    def test_edit_metadata_requires_subject_or_fields(self):
        response = self.client.post("/api/items/metadata", json={"item_ids": [1]})
        self.assertEqual(response.status_code, 422)
        response = self.client.post("/api/items/metadata", json={
            "item_ids": [1], "subject": {"source": "anilist", "id": "30002"}, "fields": {}})
        self.assertEqual(response.status_code, 422)

    def test_item_out_has_subject_source(self):
        library = self.make_library()
        self.zip("迷宫饭/Vol.01.zip")
        self.client.post("/api/libraries/{0}/scan".format(library["id"]))
        items = self.client.get("/api/items", params={"library_id": library["id"]}).json()["items"]
        self.assertEqual([(item["subject_id"], item["subject_source"]) for item in items], [("133315", "bangumi")])
        group = self.client.get("/api/history/groups").json()["groups"][0]
        self.assertEqual((group["subject_id"], group["subject_source"]), ("133315", "bangumi"))
