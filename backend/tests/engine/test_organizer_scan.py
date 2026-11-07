from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from shutong.ai.openai_compat import AiError
from shutong.engine import organizer as organizer_module
from shutong.engine.ai_recognize import BATCH_SIZE, AiNotConfigured
from shutong.engine.organizer import Organizer
from shutong.engine.states import ItemStatus, ReviewReason
from shutong.metadata.base import MetadataUnavailable, Subject
from shutong.services import EngineConfig, Services
from shutong.store.db import Database
from shutong.store.records import ItemStore, LibraryStore, RunStore

from .reader_ai import ReaderAi
from .test_ai_assist import FakeAi
from .test_match import FakeSource, subject

JPEG = b"\xff\xd8\xffsynthetic-jpeg"
DUNGEON = subject(133315, "迷宫饭", total=14)


class FlakyAi(ReaderAi):
    """ReaderAi whose recognize calls fail on the given attempts (0 is the first)."""

    def __init__(self, failures=(), **options):
        super().__init__(**options)
        self.failures = set(failures)
        self.asked = 0

    def complete_json(self, purpose, system, payload, *, item_id=None):
        if purpose == "recognize":
            attempt, self.asked = self.asked, self.asked + 1
            if attempt in self.failures:
                raise AiError("timed out")
        return super().complete_json(purpose, system, payload, item_id=item_id)


class OrganizerFixture(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.source_dir = self.root / "source"
        self.library_dir = self.root / "library"
        self.source_dir.mkdir()
        self.library_dir.mkdir()
        self.db = Database(self.root / "shutong.db")
        self.db.migrate()
        self.library = LibraryStore(self.db).create("漫画", "manga", self.source_dir, self.library_dir)
        self.items = ItemStore(self.db)
        self.source = FakeSource([DUNGEON], subjects={133315: DUNGEON})

    def organizer(self, ai=None, source=None):
        self.ai = ai or ReaderAi()
        return Organizer(Services(self.db, source or self.source, self.ai, EngineConfig()))

    def zip(self, relative):
        path = self.source_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("01.jpg", JPEG + relative.encode())
        return path

    def all_items(self):
        with self.db.connect() as connection:
            ids = [row[0] for row in connection.execute("SELECT id FROM items ORDER BY id")]
        return [self.items.get(item_id) for item_id in ids]


class OrganizerScanTests(OrganizerFixture):
    def test_scan_plans_new_sources(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("迷宫饭/迷宫饭 Vol.02.zip")
        self.organizer().scan(self.library.id)
        items = self.all_items()
        self.assertEqual([item.status for item in items], [ItemStatus.PLANNED, ItemStatus.PLANNED])
        self.assertEqual(items[0].target_path, Path("迷宫饭/迷宫饭 Vol.01.cbz"))
        self.assertEqual(items[0].subject_id, 133315)
        self.assertEqual(items[0].plan["metadata"]["series_name"], "迷宫饭")
        self.assertEqual(items[0].parsed["title_hint"], "迷宫饭")
        self.assertEqual(items[0].parsed["ai"]["confidence"], 0.97)
        kinds = [event.kind for event in self.items.events(items[0].id)]
        self.assertEqual(kinds, ["discovered", "parsed", "matched", "planned"])

    def test_scan_reports_files_done_out_of_all_found(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("迷宫饭/迷宫饭 Vol.02.zip")
        self.zip("[]/Vol.01.zip")
        organizer = self.organizer(ai=ReaderAi(unsure_series={"[]"}))
        reports = []
        organizer.on_progress = reports.append
        organizer.scan(self.library.id, on_planned=organizer.execute)
        self.assertEqual(reports[0], {"done": 0, "total": 3, "current": None})
        self.assertEqual(reports[-1]["done"], 3)
        self.assertEqual(reports[-1]["total"], 3)
        self.assertEqual({report["current"] for report in reports[1:-1]}, {"迷宫饭", "[]"})
        self.assertIsNone(reports[-1]["current"])
        dones = [report["done"] for report in reports]
        self.assertEqual(dones, sorted(dones))
        # Files settled by an earlier scan count as done straight away.
        reports.clear()
        organizer.scan(self.library.id, on_planned=organizer.execute)
        self.assertEqual((reports[-1]["done"], reports[-1]["total"]), (3, 3))

    def test_one_ai_call_per_folder_batch(self):
        for n in range(1, 4):
            self.zip("迷宫饭/迷宫饭 Vol.{0:02d}.zip".format(n))
        self.zip("葬送的芙莉莲/Vol.01.zip")
        self.organizer().scan(self.library.id)
        recognize = [request["payload"] for request in self.ai.requests if request["purpose"] == "recognize"]
        self.assertEqual(sorted((payload["folder"], len(payload["files"])) for payload in recognize),
                         [("葬送的芙莉莲", 1), ("迷宫饭", 3)])

    def test_each_folder_is_handed_over_before_the_next_is_discovered(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("迷宫饭/迷宫饭 Vol.02.zip")
        self.zip("葬送的芙莉莲/Vol.01.zip")
        organizer = self.organizer()
        handed = []

        def on_planned(ids):
            folders = {self.items.get(item_id).source_path.parent.name for item_id in ids}
            statuses = {self.items.get(item_id).status for item_id in ids}
            handed.append((folders, statuses, len(self.all_items())))

        organizer.scan(self.library.id, on_planned=on_planned)
        sizes = {"迷宫饭": 2, "葬送的芙莉莲": 1}
        [(first, first_statuses, first_seen), (second, second_statuses, second_seen)] = handed
        self.assertEqual(first | second, {"迷宫饭", "葬送的芙莉莲"})
        self.assertEqual((first_statuses, second_statuses), ({ItemStatus.PLANNED}, {ItemStatus.PLANNED}))
        # The second folder has no items yet when the first is handed over.
        self.assertEqual(first_seen, sizes[next(iter(first))])
        self.assertEqual(second_seen, 3)

    def test_long_folder_is_split_and_later_batches_keep_the_series(self):
        names = ["{0:04d} 话.zip".format(n) for n in range(1, BATCH_SIZE + 3)]
        for name in names:
            self.zip("大王饶命/" + name)
        ai = ReaderAi(answers={name: {"unit": "chapter", "number": str(index + 1), "confidence": 0.9} for index, name in enumerate(names)},
                      series={"大王饶命": {"title": "迷宫饭"}})
        self.organizer(ai=ai).scan(self.library.id)
        recognize = [request["payload"] for request in ai.requests if request["purpose"] == "recognize"]
        self.assertEqual([len(payload["files"]) for payload in recognize], [BATCH_SIZE, 2])
        self.assertNotIn("settled_series", recognize[0])
        self.assertEqual(recognize[1]["settled_series"][0]["title"], "迷宫饭")
        last = self.all_items()[-1]
        self.assertEqual(last.target_path, Path("迷宫饭/迷宫饭 Ch.{0:04d}.cbz".format(BATCH_SIZE + 2)))

    def test_library_series_and_editions_are_offered(self):
        (self.library_dir / "迷宫饭[bili电子版]").mkdir()
        (self.library_dir / "葬送的芙莉莲").mkdir()
        self.zip("迷宫饭/Vol.01.zip")
        self.organizer().scan(self.library.id)
        payload = self.ai.requests[0]["payload"]
        self.assertEqual(payload["library_series"], ["葬送的芙莉莲", "迷宫饭[bili电子版]"])
        self.assertEqual(payload["library_editions"], ["bili电子版"])

    def test_ai_title_and_edition_name_the_series(self):
        ai = ReaderAi(series={"[九井谅子][迷宫饭][Vol.01-Vol.14][完结][bili]": {"title": "迷宫饭", "edition": "bili电子版"}})
        self.zip("[九井谅子][迷宫饭][Vol.01-Vol.14][完结][bili]/Vol.01.zip")
        self.organizer(ai=ai).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual((item.status, item.subject_id), (ItemStatus.PLANNED, 133315))
        self.assertEqual(item.target_path, Path("迷宫饭[bili电子版]/迷宫饭[bili电子版] Vol.01.cbz"))

    def test_original_title_finds_the_subject(self):
        gal = Subject(subject_id=7, name="はじめてのギャル", name_cn="", summary="", release_date=None, writers=(),
                      publisher="", genres=(), completed=False, total_volumes=None, platform="漫画")
        source = FakeSource([gal], subjects={7: gal})
        ai = ReaderAi(series={"辣妹与我的第一次": {"search_titles": ["はじめてのギャル"]}})
        self.zip("辣妹与我的第一次/Vol.01.zip")
        self.organizer(ai=ai, source=source).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual((item.status, item.subject_id), (ItemStatus.PLANNED, 7))
        self.assertEqual(source.searches, [("辣妹与我的第一次", "manga"), ("はじめてのギャル", "manga")])
        self.assertEqual(item.target_path, Path("辣妹与我的第一次/辣妹与我的第一次 Vol.01.cbz"))

    def test_unsure_series_goes_to_naming_review(self):
        self.zip("[某作者][没有这部][完结]/Vol.01.zip")
        self.organizer(ai=ReaderAi(unsure_series={"[某作者][没有这部][完结]"})).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual((item.status, item.review_reason), (ItemStatus.NEEDS_REVIEW, ReviewReason.NAMING))
        suggestion = [event for event in self.items.events(item.id) if event.kind == "ai_suggestion"][0]
        self.assertEqual(suggestion.detail["title"], "[某作者][没有这部][完结]")
        self.assertEqual(self.source.searches, [])

    def test_unsure_volume_goes_to_volume_review(self):
        self.zip("迷宫饭/迷宫饭 番外.zip")
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.organizer(ai=ReaderAi(unsure={"迷宫饭 Vol.01.zip"})).scan(self.library.id)
        statuses = [(item.status, item.review_reason) for item in self.all_items()]
        self.assertEqual(statuses, [(ItemStatus.NEEDS_REVIEW, ReviewReason.VOLUME)] * 2)
        self.assertEqual(self.source.searches, [])

    def test_threshold_decides_what_is_sure(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        ai = ReaderAi(series={"迷宫饭": {"confidence": 0.9}})
        organizer = Organizer(Services(self.db, self.source, ai, EngineConfig(ai_threshold=0.95)))
        organizer.scan(self.library.id)
        self.assertEqual(self.all_items()[0].review_reason, ReviewReason.NAMING)

    def test_specials_ranges_and_chapters(self):
        ai = ReaderAi(answers={"画集.zip": {"unit": "special", "number": "1", "label": "画集", "confidence": 0.9},
                               "Vol.01-05.zip": {"number": "1", "end": "5"},
                               "第6话.zip": {"unit": "chapter", "number": "6"}})
        for name in ("画集.zip", "Vol.01-05.zip", "第6话.zip"):
            self.zip("迷宫饭/" + name)
        self.organizer(ai=ai).scan(self.library.id)
        targets = sorted(item.target_path.name for item in self.all_items())
        self.assertEqual(targets, ["迷宫饭 Ch.0006.cbz", "迷宫饭 SP01 画集.cbz", "迷宫饭 Vol.01-05.cbz"])

    def test_chapter_width_follows_the_library(self):
        (self.library_dir / "迷宫饭").mkdir()
        for n in (1, 2):
            (self.library_dir / "迷宫饭" / "迷宫饭 Ch.{0:03d}.cbz".format(n)).write_bytes(b"x")
        self.zip("迷宫饭/第3话.zip")
        self.organizer().scan(self.library.id)
        self.assertEqual(self.all_items()[0].target_path, Path("迷宫饭/迷宫饭 Ch.003.cbz"))

    def test_invalid_ai_reply_goes_to_review(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.organizer(ai=FakeAi({"series": [], "files": "nope"})).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual((item.status, item.review_reason), (ItemStatus.NEEDS_REVIEW, ReviewReason.NAMING))
        self.assertIn("AI 返回的内容不符合要求", self.items.events(item.id)[-1].detail["note"])

    def test_unreachable_ai_parks_items_for_the_next_scan(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.organizer(ai=FakeAi(AiError("timed out"), AiError("timed out"))).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual(item.status, ItemStatus.PARSED)
        self.assertIn("ai_retry", [event.kind for event in self.items.events(item.id)])
        self.organizer().scan(self.library.id)
        self.assertEqual(self.all_items()[0].status, ItemStatus.PLANNED)

    def test_ai_that_failed_is_asked_again_at_the_end_of_the_scan(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        organizer = self.organizer(ai=FlakyAi(failures=[0]))
        organizer.scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual(item.status, ItemStatus.PLANNED)
        self.assertIn("ai_retry", [event.kind for event in self.items.events(item.id)])
        self.assertEqual(self.ai.asked, 2)

    def test_files_left_waiting_for_the_ai_count_once_in_the_progress(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("迷宫饭 外传/迷宫饭 Vol.01.zip")
        organizer = self.organizer(ai=FlakyAi(failures=[0]))
        reports = []
        organizer.on_progress = reports.append
        organizer.scan(self.library.id, on_planned=organizer.execute)
        self.assertEqual({report["total"] for report in reports}, {2})
        self.assertEqual(reports[-1]["done"], 2)
        self.assertEqual(max(report["done"] for report in reports), 2)

    def test_retry_keeps_the_series_the_folder_already_settled_on(self):
        for number in range(1, BATCH_SIZE + 2):
            self.zip("迷宫饭/迷宫饭 Vol.{0:03d}.zip".format(number))
        organizer = self.organizer(ai=FlakyAi(failures=[1], series={"迷宫饭": {"edition": "东立"}}))
        organizer.scan(self.library.id)
        recognize = [request for request in self.ai.requests if request["purpose"] == "recognize"]
        self.assertEqual(len(recognize), 2)  # the failed call is not in requests
        self.assertEqual(recognize[-1]["payload"]["settled_series"][0]["edition"], "东立")
        self.assertEqual({item.status for item in self.all_items()}, {ItemStatus.PLANNED})

    def test_stops_asking_an_ai_that_keeps_failing(self):
        for number in range(1, 7):
            self.zip("作品{0}/作品{0} Vol.01.zip".format(number))
        self.organizer(ai=FlakyAi(failures=range(100))).scan(self.library.id)
        self.assertEqual(self.ai.asked, 3)
        items = self.all_items()
        self.assertEqual({item.status for item in items}, {ItemStatus.PARSED})
        for item in items:
            self.assertIn("ai_retry", [event.kind for event in self.items.events(item.id)])

    def test_a_scan_told_to_stop_leaves_later_folders_for_the_next_one(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("迷宫饭 外传/迷宫饭 Vol.01.zip")
        organizer = self.organizer()
        organizer.should_stop = lambda: bool(self.all_items())
        organizer.scan(self.library.id)
        self.assertEqual(len(self.all_items()), 1)
        self.organizer().scan(self.library.id)
        self.assertEqual(len(self.all_items()), 2)

    def test_stopping_during_a_batch_leaves_the_rest_planned(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("迷宫饭/迷宫饭 Vol.02.zip")
        organizer = self.organizer()
        organizer.scan(self.library.id)
        items = self.all_items()
        organizer.should_stop = lambda: any(self.items.get(item.id).status is ItemStatus.PUBLISHED for item in items)
        organizer.execute([item.id for item in items])
        self.assertEqual([self.items.get(item.id).status for item in items],
                         [ItemStatus.PUBLISHED, ItemStatus.PLANNED])

    def sub_series(self, source, **options):
        self.zip("迷宫饭 外传/迷宫饭 外传 Vol.01.zip")
        ai = ReaderAi(series={"迷宫饭 外传": {"base_title": "迷宫饭"}}, **options)
        self.organizer(ai=ai, source=source).scan(self.library.id)
        return self.all_items()[-1]

    def test_sub_series_with_its_own_entry_stays_separate(self):
        own = subject(200, "迷宫饭 外传", total=1)
        item = self.sub_series(FakeSource([DUNGEON, own], subjects={133315: DUNGEON, 200: own}), choose=200)
        self.assertEqual((item.status, item.subject_id), (ItemStatus.PLANNED, 200))
        self.assertEqual(item.target_path.parent.name, "迷宫饭 外传")

    def test_a_clear_search_winner_for_the_original_does_not_count_as_its_own_entry(self):
        item = self.sub_series(self.source, choose=0, choose_confidence=0.95)
        self.assertEqual((item.status, item.subject_id), (ItemStatus.PLANNED, 133315))
        self.assertEqual(item.target_path.parent.name, "迷宫饭")
        self.assertEqual(item.target_path.name, "迷宫饭 SP01 外传 1.cbz")
        self.assertIn("merged_into_original", [event.kind for event in self.items.events(item.id)])
        question = [request for request in self.ai.requests if request["purpose"] == "choose_subject"][-1]
        self.assertEqual(question["payload"]["base_title"], "迷宫饭")

    def test_sub_series_merged_into_the_original_does_not_clash_with_its_volumes(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        ai = ReaderAi(series={"迷宫饭 外传": {"base_title": "迷宫饭"}}, choose=0, choose_confidence=0.95)
        organizer = self.organizer(ai=ai)
        organizer.scan(self.library.id, on_planned=organizer.execute)
        self.zip("迷宫饭 外传/迷宫饭 外传 Vol.01.zip")
        organizer.scan(self.library.id, on_planned=organizer.execute)
        self.assertEqual({item.status for item in self.all_items()}, {ItemStatus.PUBLISHED})
        self.assertEqual(sorted(path.name for path in (self.library_dir / "迷宫饭").iterdir()),
                         ["迷宫饭 SP01 外传 1.cbz", "迷宫饭 Vol.01.cbz"])

    def test_sub_series_goes_to_review_when_the_ai_is_unsure_there_is_no_entry(self):
        item = self.sub_series(self.source, choose=0, choose_confidence=0.3)
        self.assertEqual((item.status, item.review_reason), (ItemStatus.NEEDS_REVIEW, ReviewReason.METADATA))

    def test_sub_series_goes_to_review_when_the_original_is_not_on_bangumi_either(self):
        item = self.sub_series(FakeSource([]))
        self.assertEqual((item.status, item.review_reason), (ItemStatus.NEEDS_REVIEW, ReviewReason.METADATA))
        self.assertEqual(self.items.get(item.id).parsed["title_hint"], "迷宫饭 外传")

    def test_a_title_chosen_in_review_is_not_treated_as_a_sub_series(self):
        item = self.sub_series(self.source, choose=0, choose_confidence=0.3)
        organizer = self.organizer(ai=ReaderAi(series={"迷宫饭 外传": {"base_title": "迷宫饭"}}))
        organizer.confirm([item.id], title="迷宫饭 外传", bgm=133315)
        after = self.items.get(item.id)
        self.assertEqual((after.status, after.target_path.parent.name), (ItemStatus.PLANNED, "迷宫饭 外传"))
        self.assertEqual(after.target_path.name, "迷宫饭 外传 Vol.01.cbz")

    def test_scan_needs_ai(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        organizer = Organizer(Services(self.db, self.source, None, EngineConfig()))
        with self.assertRaises(AiNotConfigured):
            organizer.scan(self.library.id)
        self.assertEqual(self.all_items(), [])

    def test_review_choices_skip_the_ai(self):
        self.zip("迷宫饭/迷宫饭 番外.zip")
        organizer = self.organizer()
        organizer.scan(self.library.id)
        [item] = self.all_items()
        calls = len(self.ai.requests)
        organizer.confirm([item.id], title="迷宫饭", volumes={item.id: "SP1"})
        self.assertEqual(len(self.ai.requests), calls)
        self.assertEqual(self.items.get(item.id).overrides, {"title": "迷宫饭", "volume": "SP1"})
        self.assertEqual(self.items.get(item.id).target_path, Path("迷宫饭/迷宫饭 SP01.cbz"))

    def test_reidentify_reads_review_items_again(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("[某作者][没有这部]/Vol.01.zip")
        organizer = self.organizer(ai=ReaderAi(unsure_series={"迷宫饭", "[某作者][没有这部]"}))
        organizer.scan(self.library.id)
        self.assertEqual({item.status for item in self.all_items()}, {ItemStatus.NEEDS_REVIEW})
        later = self.organizer(ai=ReaderAi(unsure_series={"[某作者][没有这部]"}))
        counts = later.reidentify([item.id for item in self.all_items()])
        self.assertEqual(counts, {"planned": 1, "needs_review": 1, "skipped": 0})

    def test_reidentify_keeps_items_in_review_when_bangumi_is_unreachable(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.organizer().scan(self.library.id)
        with self.db.connect() as connection:
            connection.execute("UPDATE items SET status = 'needs_review', review_reason = 'metadata', target_path = NULL")
        offline = FakeSource(error=MetadataUnavailable("Bangumi unavailable after 3 attempts"))
        [item] = self.all_items()
        counts = self.organizer(source=offline).reidentify([item.id])
        self.assertEqual(counts, {"needs_review": 1, "skipped": 0})
        self.assertEqual(self.items.events(item.id)[-1].detail["note"], "AI 或 Bangumi 暂时无法访问，稍后再重新识别")

    def test_reidentify_survives_one_bad_item_and_unknown_ids(self):
        for n in (1, 2):
            self.zip("迷宫饭/迷宫饭 Vol.{0:02d}.zip".format(n))
        organizer = self.organizer()
        organizer.scan(self.library.id)
        first, second = self.all_items()
        with self.db.connect() as connection:
            connection.execute("UPDATE items SET status = 'needs_review', review_reason = 'volume', target_path = NULL")
            # Scanned under an older source dir: its path is no longer inside this library.
            connection.execute("UPDATE items SET source_path = '/elsewhere/迷宫饭/迷宫饭 Vol.01.zip' WHERE id = ?", (first.id,))
        counts = organizer.reidentify([first.id, second.id, 99999])
        self.assertEqual(self.items.get(second.id).status, ItemStatus.PLANNED)
        self.assertEqual(self.items.get(first.id).status, ItemStatus.CANCELLED)  # its source is gone
        self.assertEqual(counts["skipped"], 1)

    def test_reidentify_cancels_items_whose_source_is_gone(self):
        source = self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        organizer = self.organizer()
        organizer.scan(self.library.id)
        [item] = self.all_items()
        with self.db.connect() as connection:
            connection.execute("UPDATE items SET status = 'needs_review', review_reason = 'volume'")
        source.unlink()
        organizer.reidentify([item.id])
        self.assertEqual(self.items.get(item.id).status, ItemStatus.CANCELLED)
        self.assertIn("source_missing", [event.kind for event in self.items.events(item.id)])

    def test_reidentify_skips_items_not_in_review(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        organizer = self.organizer()
        organizer.scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual(organizer.reidentify([item.id]), {"skipped": 1})
        self.assertIs(self.items.get(item.id).status, ItemStatus.PLANNED)

    def test_rescan_does_not_duplicate_items(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        organizer = self.organizer()
        organizer.scan(self.library.id)
        run_id = organizer.scan(self.library.id)
        self.assertEqual(len(self.all_items()), 1)
        with self.db.connect() as connection:
            counts = connection.execute("SELECT counts FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
        self.assertIn('"known": 1', counts)

    def test_ai_asked_once_per_series_folder_for_the_subject(self):
        other = subject(9, "完全不同的名字")
        source = FakeSource([other], subjects={9: other})
        ai = ReaderAi(choose=0)
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("迷宫饭/迷宫饭 Vol.02.zip")
        self.organizer(ai=ai, source=source).scan(self.library.id)
        self.assertEqual(ai.purposes(), ["recognize", "choose_subject"])

    def test_no_fitting_bangumi_subject_goes_to_review(self):
        other = subject(9, "完全不同的名字")
        source = FakeSource([other], subjects={9: other})
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        # Even when the AI is sure none of the candidates is this series, the user decides in review.
        self.organizer(ai=ReaderAi(choose=0, choose_confidence=0.98), source=source).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual((item.status, item.review_reason), (ItemStatus.NEEDS_REVIEW, ReviewReason.METADATA))
        self.assertNotIn("no_metadata", [event.kind for event in self.items.events(item.id)])
        review = [event for event in self.items.events(item.id) if event.kind == "review"][-1]
        self.assertEqual(review.detail["note"], "Bangumi 候选里没有这部作品")

    def test_nothing_on_bangumi_goes_to_review(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.organizer(source=FakeSource([], subjects={})).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual((item.status, item.review_reason), (ItemStatus.NEEDS_REVIEW, ReviewReason.METADATA))
        review = [event for event in self.items.events(item.id) if event.kind == "review"][-1]
        self.assertEqual(review.detail["note"], "Bangumi 上没有搜到")

    def test_an_unsure_pick_among_candidates_goes_to_review(self):
        maybe = subject(9, "另一部作品")
        source = FakeSource([maybe], subjects={9: maybe})
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.organizer(ai=ReaderAi(choose=9, choose_confidence=0.6), source=source).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual((item.status, item.review_reason), (ItemStatus.NEEDS_REVIEW, ReviewReason.METADATA))
        self.assertNotIn("no_metadata", [event.kind for event in self.items.events(item.id)])
        review = [event for event in self.items.events(item.id) if event.kind == "review"][-1]
        self.assertEqual(review.detail["candidates"], [9])

    def test_unsure_that_nothing_fits_goes_to_review(self):
        other = subject(9, "完全不同的名字")
        source = FakeSource([other], subjects={9: other})
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.organizer(ai=ReaderAi(choose=0, choose_confidence=0.5), source=source).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual((item.status, item.review_reason), (ItemStatus.NEEDS_REVIEW, ReviewReason.METADATA))

    def test_unsure_series_without_subject_still_goes_to_review(self):
        source = FakeSource([], subjects={})
        ai = ReaderAi(unsure_series=["迷宫饭"])
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.organizer(ai=ai, source=source).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual(item.status, ItemStatus.NEEDS_REVIEW)

    def test_rescan_follows_a_renamed_source(self):
        old = self.zip("[作者][迷宫饭]/Vol.01.zip")
        organizer = self.organizer()
        organizer.scan(self.library.id)
        new_folder = self.source_dir / "迷宫饭 新目录"
        old.parent.rename(new_folder)
        organizer.scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual(item.source_path, new_folder / "Vol.01.zip")
        self.assertEqual(item.group_key, "迷宫饭 新目录")
        self.assertEqual(organizer.execute([item.id])["published"], 1)

    def test_ai_subject_choice_is_adopted(self):
        other = subject(9, "完全不同的名字")
        source = FakeSource([other], subjects={9: other})
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.organizer(source=source).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual((item.status, item.subject_id), (ItemStatus.PLANNED, 9))
        self.assertIn("ai_adopted", [event.kind for event in self.items.events(item.id)])

    def test_metadata_unavailable_parks_items_and_replan_recovers(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("迷宫饭/迷宫饭 Vol.02.zip")
        offline = FakeSource(error=MetadataUnavailable("Bangumi unavailable after 3 attempts"))
        self.organizer(source=offline).scan(self.library.id)
        items = self.all_items()
        self.assertEqual({item.status for item in items}, {ItemStatus.PARSED})
        self.assertIn("metadata_retry", [event.kind for event in self.items.events(items[0].id)])
        self.organizer().replan([item.id for item in items])
        self.assertEqual({item.status for item in self.all_items()}, {ItemStatus.PLANNED})

    def test_config_error_parks_item(self):
        import io
        from urllib.error import HTTPError

        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        bad_token = FakeSource(error=HTTPError("https://api.bgm.tv", 401, "Unauthorized", {}, io.BytesIO()))
        self.organizer(source=bad_token).scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual(item.status, ItemStatus.PARSED)
        self.assertIn("metadata_config_error", [event.kind for event in self.items.events(item.id)])

    def test_unexpected_error_fails_one_item_not_the_scan(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("迷宫饭/迷宫饭 Vol.02.zip")
        real = organizer_module.Organizer._recognize_and_match

        def flaky(organizer, item_id, library, adapter, entry):
            if "Vol.01" in entry.path.name:
                raise RuntimeError("boom")
            return real(organizer, item_id, library, adapter, entry)

        with mock.patch.object(organizer_module.Organizer, "_recognize_and_match", flaky):
            self.organizer().scan(self.library.id)
        statuses = [item.status for item in self.all_items()]
        self.assertEqual(statuses, [ItemStatus.FAILED, ItemStatus.PLANNED])
        self.assertIn("boom", self.all_items()[0].error)

    def test_existing_volume_becomes_duplicate(self):
        (self.library_dir / "迷宫饭").mkdir()
        (self.library_dir / "迷宫饭" / "迷宫饭 Vol.01.cbz").write_bytes(b"x")
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        run_id = self.organizer().scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual(item.status, ItemStatus.DUPLICATE)
        with self.db.connect() as connection:
            counts = connection.execute("SELECT counts, finished_at FROM runs WHERE id = ?", (run_id,)).fetchone()
        self.assertIn('"duplicate": 1', counts[0])
        self.assertIsNotNone(counts[1])
        self.assertIsNotNone(RunStore)

    def test_identical_files_in_one_scan_are_processed_once(self):
        for folder in ("迷宫饭", "迷宫饭 备份"):
            path = self.source_dir / folder / "迷宫饭 Vol.01.zip"
            path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("01.jpg", JPEG + b"same bytes")
        run_id = self.organizer().scan(self.library.id)
        [item] = self.all_items()
        self.assertEqual(item.status, ItemStatus.PLANNED)
        self.assertEqual([e.kind for e in self.items.events(item.id)].count("parsed"), 1)
        self.assertEqual(RunStore(self.db).counts(run_id).get("known"), 1)

    def test_planning_error_on_one_item_does_not_abort_the_scan(self):
        self.zip("迷宫饭/迷宫饭 Vol.01.zip")
        self.zip("迷宫饭/迷宫饭 Vol.02.zip")
        from shutong.store.records import ItemStore as Store
        real = Store.transition

        def flaky(store, item_id, target, **kwargs):
            if target is ItemStatus.PLANNED and kwargs.get("target_path") and "Vol.01" in str(kwargs["target_path"]):
                raise RuntimeError("disk hiccup")
            return real(store, item_id, target, **kwargs)

        with mock.patch.object(Store, "transition", flaky):
            run_id = self.organizer().scan(self.library.id)
        statuses = sorted(item.status.value for item in self.all_items())
        self.assertEqual(statuses, ["failed", "planned"])
        self.assertIsNotNone(RunStore(self.db).counts(run_id))


if __name__ == "__main__":
    unittest.main()
