"""Organizing with more than one metadata source: asked in order, never switching on a temporary failure."""
from dataclasses import replace
import unittest
import zipfile

from shutong.engine.states import ItemStatus, ReviewReason
from shutong.metadata.base import MetadataUnavailable, SubjectRef
from shutong.metadata.registry import SourceRegistry
from shutong.engine.organizer import Organizer
from shutong.services import EngineConfig, Services

from .reader_ai import ReaderAi
from .test_match import FakeSource, subject
from .test_organizer_scan import DUNGEON, OrganizerFixture


def organizer_entry(path):
    from shutong.engine.kinds.base import SourceEntry
    return SourceEntry(path, "archive", path.parent.name, None)


class Named(FakeSource):
    def __init__(self, name, results=(), subjects=None, error=None):
        results = tuple(replace(entry, source=name) for entry in results)
        subjects = {key: replace(value, source=name) for key, value in (subjects or {}).items()}
        super().__init__(results, subjects, error)
        self.name = name
        self.label = name.upper()


class Titled(Named):
    """Answers only searches for a title it has."""

    def search(self, query, kind):
        return tuple(entry for entry in super().search(query, kind) if query in (entry.name_cn, entry.name))


ANI_DUNGEON = replace(subject(30002, "迷宫饭", total=14))


class MultiSourceTests(OrganizerFixture):
    def organizer_with(self, *sources, ai=None):
        registry = SourceRegistry({source.name: source for source in sources}, [source.name for source in sources])
        self.ai = ai or ReaderAi()
        return Organizer(Services(self.db, registry, self.ai, EngineConfig()))

    def test_second_source_when_first_finds_nothing(self):
        a, b = Named("a"), Named("b", [ANI_DUNGEON], {30002: ANI_DUNGEON})
        self.zip("迷宫饭/Vol.01.zip")
        self.organizer_with(a, b).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual((item.status, item.subject_id, item.subject_source), (ItemStatus.PLANNED, "30002", "b"))
        self.assertTrue(a.searches)

    def test_unavailable_first_source_does_not_fall_through(self):
        a = Named("a", error=MetadataUnavailable("timeout"))
        b = Named("b", [ANI_DUNGEON], {30002: ANI_DUNGEON})
        self.zip("迷宫饭/Vol.01.zip")
        self.organizer_with(a, b).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual(item.status, ItemStatus.PARSED)
        self.assertIn("metadata_retry", [event.kind for event in self.items.events(item.id)])
        self.assertEqual(b.searches, [])

    def test_unsure_ai_goes_to_review_without_next_source(self):
        other = subject(5, "地下城美食", total=2)
        a = Named("a", [other, subject(6, "迷宫餐厅")], {5: other})
        b = Named("b", [ANI_DUNGEON], {30002: ANI_DUNGEON})
        self.zip("迷宫饭/Vol.01.zip")
        self.organizer_with(a, b, ai=ReaderAi(choose_confidence=0.5)).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual((item.status, item.review_reason), (ItemStatus.NEEDS_REVIEW, ReviewReason.METADATA))
        self.assertEqual(b.searches, [])

    def test_ai_sure_nothing_fits_tries_next_source(self):
        a = Named("a", [subject(5, "地下城美食", total=2), subject(6, "迷宫餐厅")])
        b = Named("b", [ANI_DUNGEON], {30002: ANI_DUNGEON})
        self.zip("迷宫饭/Vol.01.zip")
        self.organizer_with(a, b, ai=ReaderAi(choose=0, choose_confidence=0.99)).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual((item.status, item.subject_source), (ItemStatus.PLANNED, "b"))

    def test_all_sources_empty_goes_to_review(self):
        self.zip("迷宫饭/Vol.01.zip")
        self.organizer_with(Named("a"), Named("b")).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual((item.status, item.review_reason), (ItemStatus.NEEDS_REVIEW, ReviewReason.METADATA))
        review = [event for event in self.items.events(item.id) if event.kind == "review"][-1]
        self.assertEqual(review.detail["note"], "A 上没有搜到")

    def test_folder_keeps_its_source(self):
        a = Named("a")
        b = Named("b", [ANI_DUNGEON], {30002: ANI_DUNGEON})
        self.zip("迷宫饭/Vol.01.zip")
        self.organizer_with(a, b).scan(self.library.id)
        # Later the first source learns of the series too: the folder still keeps what it was organized from.
        a2 = Named("a", [DUNGEON], {133315: DUNGEON})
        b2 = Named("b", [ANI_DUNGEON], {30002: ANI_DUNGEON})
        self.zip("迷宫饭/Vol.02.zip")
        self.organizer_with(a2, b2).scan(self.library.id)
        items = self.all_items()
        self.assertEqual([item.subject_source for item in items], ["b", "b"])
        self.assertEqual(a2.searches, [])

    def test_folder_lock_ignores_a_source_switched_off(self):
        a = Named("a")
        b = Named("b", [ANI_DUNGEON], {30002: ANI_DUNGEON})
        self.zip("迷宫饭/Vol.01.zip")
        self.organizer_with(a, b).scan(self.library.id)
        # The second source is switched off: new files are matched as if it never existed.
        a2 = Named("a", [DUNGEON], {133315: DUNGEON})
        b2 = Named("b", [ANI_DUNGEON], {30002: ANI_DUNGEON})
        self.zip("迷宫饭/Vol.02.zip")
        registry = SourceRegistry({"a": a2, "b": b2}, ["a"])
        Organizer(Services(self.db, registry, ReaderAi(), EngineConfig())).scan(self.library.id)
        self.assertEqual([item.subject_source for item in self.all_items()], ["b", "a"])
        self.assertEqual(b2.searches, [])

    def test_loose_dropped_files_do_not_share_a_lock(self):
        from shutong.engine.dropped import resolve_drops
        from shutong.engine.kinds.manga.adapter import MangaAdapter
        downloads = self.root / "Downloads"
        downloads.mkdir()
        for name in ("迷宫饭 Vol.01.zip", "别的书 Vol.01.zip"):
            with zipfile.ZipFile(downloads / name, "w") as archive:
                archive.writestr("01.jpg", b"\xff\xd8\xff" + name.encode())
        other = subject(7, "别的书", total=3)
        a = Titled("a", [other], {7: other})  # only knows the second book
        b = Titled("b", [ANI_DUNGEON], {30002: ANI_DUNGEON})

        class PerFileAi(ReaderAi):  # a folder of unrelated loose files: each file is its own work
            def complete_json(self, purpose, system, payload, *, item_id=None):
                if purpose != "choose_subject":
                    payload = dict(payload, folder="")
                return super().complete_json(purpose, system, payload, item_id=item_id)

        ai = PerFileAi(series={"迷宫饭 Vol.01.zip": {"title": "迷宫饭"}, "别的书 Vol.01.zip": {"title": "别的书"}})
        entries = resolve_drops(MangaAdapter(), [downloads / "迷宫饭 Vol.01.zip", downloads / "别的书 Vol.01.zip"],
                                self.library_dir).entries
        self.organizer_with(a, b, ai=ai).scan_paths(self.library.id, entries)
        sources = {item.source_path.name: item.subject_source for item in self.all_items()}
        self.assertEqual(sources, {"迷宫饭 Vol.01.zip": "b", "别的书 Vol.01.zip": "a"})

    def test_a_sub_series_does_not_lock_its_folder(self):
        self.zip("迷宫饭/Vol.01.zip")
        organizer = self.organizer_with(Named("a"), Named("b", [ANI_DUNGEON], {30002: ANI_DUNGEON}))
        organizer._remember_source(self.library, organizer_entry(self.source_dir / "迷宫饭/Vol.01.zip"),
                                   replace(ANI_DUNGEON, source="b"), sub_series=True)
        self.assertEqual(organizer._folder_sources, {})

    def test_legacy_bgm_override_is_honored(self):
        bangumi = Named("bangumi", [], {7: subject(7, "迷宫饭", total=14)})
        self.zip("迷宫饭/Vol.01.zip")
        organizer = self.organizer_with(bangumi, ai=ReaderAi(unsure_series=("迷宫饭",)))
        organizer.scan(self.library.id)
        [item] = self.all_items()
        self.items.set_overrides(item.id, {"bgm": 7, "title": "迷宫饭"})
        organizer.confirm([item.id])
        item = self.items.get(item.id)
        self.assertEqual((item.status, item.subject_id, item.subject_source), (ItemStatus.PLANNED, "7", "bangumi"))
        self.assertIn(("7", False), bangumi.gets)

    def test_confirm_with_another_source_subject(self):
        a = Named("a")
        b = Named("b", [], {30002: ANI_DUNGEON})
        self.zip("迷宫饭/Vol.01.zip")
        organizer = self.organizer_with(a, b)
        organizer.scan(self.library.id)
        [item] = self.all_items()
        organizer.confirm([item.id], subject=SubjectRef("b", "30002"))
        item = self.items.get(item.id)
        self.assertEqual(item.overrides.get("subject"), {"source": "b", "id": "30002"})
        self.assertNotIn("bgm", item.overrides)
        self.assertEqual((item.status, item.subject_id, item.subject_source), (ItemStatus.PLANNED, "30002", "b"))

    def test_confirm_rejects_an_unknown_source(self):
        self.zip("迷宫饭/Vol.01.zip")
        organizer = self.organizer_with(Named("a"))
        organizer.scan(self.library.id)
        [item] = self.all_items()
        with self.assertRaises(ValueError):
            organizer.confirm([item.id], subject=SubjectRef("douban", "1"))

    def test_refresh_uses_the_items_own_source(self):
        a = Named("a", [], {})
        b = Named("b", [ANI_DUNGEON], {30002: ANI_DUNGEON})
        self.zip("迷宫饭/Vol.01.zip")
        organizer = self.organizer_with(a, b)
        organizer.scan(self.library.id)
        [item] = self.all_items()
        organizer.execute([item.id])
        b.gets.clear()
        # The source has been switched off since: the item still refreshes from it.
        registry = SourceRegistry({"a": a, "b": b}, ["a"])
        Organizer(Services(self.db, registry, self.ai, EngineConfig())).refresh_metadata([item.id])
        self.assertEqual(b.gets, [("30002", True)])
        self.assertEqual(a.gets, [])


if __name__ == "__main__":
    unittest.main()
