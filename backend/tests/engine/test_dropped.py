"""What a drop on the window turns into: entries with a root, and nothing but what was dropped."""
from pathlib import Path
import unicodedata
import zipfile

from shutong.engine.dropped import resolve_drops
from shutong.engine.kinds.manga.adapter import MangaAdapter
from shutong.engine.kinds.novel.adapter import NovelAdapter
from shutong.engine.organizer import Organizer
from shutong.engine.states import ItemStatus
from shutong.store.records import LibraryStore

from .test_ai_assist import FakeAi
from .test_organizer_scan import JPEG, OrganizerFixture


class DropFixture(OrganizerFixture):
    def setUp(self):
        super().setUp()
        self.drops = self.root / "下载"
        self.drops.mkdir()
        self.manga = MangaAdapter(pdf_to_cbz=True)

    def make(self, relative, data=b"x"):
        path = self.drops / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".zip":
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("01.jpg", JPEG + relative.encode())
        else:
            path.write_bytes(data)
        return path

    def resolve(self, *paths, adapter=None):
        return resolve_drops(adapter or self.manga, paths, self.library_dir)

    def folders(self, result):
        return {entry.path.name: entry.series_folder for entry in result.entries}


class ResolveTests(DropFixture):
    def test_single_file_ignores_siblings(self):
        wanted = self.make("迷宫饭 Vol.01.zip")
        self.make("其他.zip")
        result = self.resolve(wanted)
        self.assertEqual([entry.path for entry in result.entries], [wanted])
        # Vol.01.zip alone says nothing: the folder it was dropped from is what the AI has to go on.
        self.assertEqual((result.entries[0].root, result.entries[0].series_folder), (self.drops, "下载"))

    def test_folder_of_archives_is_one_series(self):
        self.make("迷宫饭/1.zip")
        self.make("其他/2.zip")
        result = self.resolve(self.drops / "迷宫饭")
        self.assertEqual(self.folders(result), {"1.zip": "迷宫饭"})
        self.assertEqual(result.entries[0].root, self.drops)

    def test_volumes_as_image_folders(self):
        self.make("迷宫饭/卷1/01.jpg", JPEG)
        self.make("迷宫饭/卷2/01.jpg", JPEG)
        result = self.resolve(self.drops / "迷宫饭")
        self.assertEqual(self.folders(result), {"卷1": "迷宫饭", "卷2": "迷宫饭"})
        self.assertEqual({entry.kind for entry in result.entries}, {"folder"})

    def test_a_dropped_image_folder_is_one_book(self):
        self.make("某话/01.jpg", JPEG)
        result = self.resolve(self.drops / "某话")
        self.assertEqual([(entry.path.name, entry.kind, entry.series_folder, entry.root) for entry in result.entries],
                         [("某话", "folder", "下载", self.drops)])

    def test_collection_folder_splits_series(self):
        self.make("合集/A/1.zip")
        self.make("合集/B/2.zip")
        result = self.resolve(self.drops / "合集")
        self.assertEqual(self.folders(result), {"1.zip": "A", "2.zip": "B"})
        self.assertEqual(result.entries[0].root, self.drops / "合集")

    def test_mixed_collection_stays_one_folder(self):
        self.make("合集/a.zip")
        self.make("合集/B/b.zip")
        self.assertEqual(self.folders(self.resolve(self.drops / "合集")), {"a.zip": "合集", "b.zip": "合集"})

    def test_collection_with_a_stray_file_still_splits_series(self):
        self.make("合集/杂志.zip")
        for relative in ("合集/A/1.zip", "合集/A/2.zip", "合集/B/3.zip", "合集/B/4.zip"):
            self.make(relative)
        result = self.resolve(self.drops / "合集")
        self.assertEqual({key: value for key, value in self.folders(result).items() if key != "杂志.zip"},
                         {"1.zip": "A", "2.zip": "A", "3.zip": "B", "4.zip": "B"})
        self.assertEqual(result.entries[0].root, self.drops / "合集")

    def test_series_with_an_extras_folder_stays_one_series(self):
        for relative in ("迷宫饭/1.zip", "迷宫饭/2.zip", "迷宫饭/番外/x.zip"):
            self.make(relative)
        result = self.resolve(self.drops / "迷宫饭")
        self.assertEqual(set(self.folders(result).values()), {"迷宫饭"})

    def test_light_novels(self):
        one = self.make("书/1.epub")
        self.make("书/2.txt")
        self.make("合集/甲/1.epub")
        novel = NovelAdapter()
        self.assertEqual(self.folders(self.resolve(self.drops / "书", adapter=novel)), {"1.epub": "书"})
        self.assertEqual(self.folders(self.resolve(self.drops / "合集", adapter=novel)), {"1.epub": "甲"})
        self.assertEqual(self.resolve(one, adapter=novel).entries[0].kind, "epub")
        self.assertEqual(self.resolve(self.make("x.zip"), adapter=novel).skipped[0].reason, "unsupported")

    def test_unsupported_file_is_reported(self):
        result = self.resolve(self.make("说明.txt"))
        self.assertEqual((result.entries, result.skipped[0].reason), ((), "unsupported"))

    def test_folder_with_nothing_to_organize_is_reported(self):
        self.make("文档/说明.txt")
        self.assertEqual(self.resolve(self.drops / "文档").skipped[0].reason, "empty")

    def test_missing_path_is_reported(self):
        self.assertEqual(self.resolve(self.drops / "没有").skipped[0].reason, "missing")

    def test_hidden_file_is_ignored(self):
        self.assertEqual(self.resolve(self.make(".DS_Store")).skipped[0].reason, "unsupported")

    def test_inside_library_rejected(self):
        path = self.library_dir / "迷宫饭" / "1.zip"
        path.parent.mkdir()
        path.write_bytes(b"x")
        result = self.resolve(path)
        self.assertEqual((result.entries, result.rejected), ((), (path,)))

    def test_containing_library_rejected(self):
        self.assertEqual(self.resolve(self.root).rejected, (self.root,))
        self.assertEqual(self.resolve(self.library_dir).rejected, (self.library_dir,))

    def test_overlapping_drops_count_once(self):
        file = self.make("迷宫饭/1.zip")
        self.assertEqual(len(self.resolve(file, self.drops / "迷宫饭").entries), 1)

    def test_nfd_folder_name_reads_as_nfc(self):
        decomposed = unicodedata.normalize("NFD", "ガンダム")
        self.make(decomposed + "/1.zip")
        result = self.resolve(self.drops / decomposed)
        self.assertEqual(result.entries[0].series_folder, unicodedata.normalize("NFC", "ガンダム"))


class ScanPathsTests(DropFixture):
    def setUp(self):
        super().setUp()
        self.library = LibraryStore(self.db).create("桌面", "manga", "", self.library_dir, source_policy="keep")

    def drop(self, *paths):
        organizer = self.organizer()
        published = []

        def publish(ids):
            published.extend(ids)
            organizer.execute(ids)

        result = resolve_drops(MangaAdapter(pdf_to_cbz=True), paths, self.library_dir)
        organizer.scan_paths(self.library.id, result.entries, on_planned=publish)
        return organizer

    def test_keeps_originals_and_publishes(self):
        source = self.make("迷宫饭/迷宫饭 Vol.01.zip")
        self.make("其他/别动.zip")
        self.drop(self.drops / "迷宫饭")
        item = self.all_items()[0]
        self.assertEqual(len(self.all_items()), 1)
        self.assertEqual((item.status, item.source_root), (ItemStatus.PUBLISHED, self.drops))
        self.assertTrue(source.exists())
        self.assertTrue((self.library_dir / "迷宫饭" / "迷宫饭 Vol.01.cbz").exists())

    def test_ai_sees_only_the_folder_and_file_names(self):
        self.make("迷宫饭/迷宫饭 Vol.01.zip")
        organizer = self.drop(self.drops / "迷宫饭")
        payload = next(request["payload"] for request in self.ai.requests if request["purpose"] == "recognize")
        self.assertEqual((payload["folder"], payload["files"]), ("迷宫饭", ["迷宫饭 Vol.01.zip"]))
        self.assertNotIn(str(self.root), str(payload))
        self.assertIsNotNone(organizer)

    def test_redrop_creates_no_duplicates(self):
        self.make("迷宫饭/迷宫饭 Vol.01.zip")
        self.drop(self.drops / "迷宫饭")
        self.drop(self.drops / "迷宫饭")
        self.assertEqual(len(self.all_items()), 1)

    def test_same_bytes_elsewhere_one_item(self):
        first = self.make("迷宫饭/迷宫饭 Vol.01.zip")
        copy = self.drops / "副本" / "迷宫饭" / "迷宫饭 Vol.01.zip"
        copy.parent.mkdir(parents=True)
        copy.write_bytes(first.read_bytes())
        self.drop(self.drops / "迷宫饭")
        self.drop(copy.parent)
        self.assertEqual(len(self.all_items()), 1)

    def test_moved_then_redropped_follows_the_new_place(self):
        first = self.make("迷宫饭/迷宫饭 Vol.01.zip")
        self.drop(self.drops / "迷宫饭")
        moved = self.root / "新家" / "迷宫饭"
        moved.parent.mkdir()
        first.parent.rename(moved)
        self.drop(moved)
        item = self.all_items()[0]
        self.assertEqual((item.source_path, item.source_root), (moved / first.name, moved.parent))

    def test_replan_after_drop_uses_the_items_root(self):
        self.make("[]看不懂/x Vol.01.zip")
        self.drop(self.drops / "[]看不懂")
        item = self.all_items()[0]
        self.assertEqual(item.status, ItemStatus.NEEDS_REVIEW)
        organizer = self.organizer()
        organizer.confirm([item.id], title="迷宫饭", bgm=133315)
        self.assertNotEqual(self.items.get(item.id).status, ItemStatus.FAILED)

    def test_reorganize_after_drop_keeps_the_original(self):
        source = self.make("迷宫饭/迷宫饭 Vol.01.zip")
        self.drop(self.drops / "迷宫饭")
        item = self.all_items()[0]
        organizer = self.organizer()
        organizer.reorganize([item.id], title="迷宫饭")
        self.assertTrue(source.exists())
        self.assertNotEqual(self.items.get(item.id).status, ItemStatus.FAILED)

    def test_scan_of_the_library_does_not_touch_dropped_items(self):
        self.make("迷宫饭/迷宫饭 Vol.01.zip")
        self.drop(self.drops / "迷宫饭")
        Organizer.scan(self.organizer(), self.library.id)
        self.assertEqual(self.all_items()[0].status, ItemStatus.PUBLISHED)


def _reading(*titles):
    """One AI answer per file: ``(name, title)``, or ``(name, None)`` for a file it could not place."""
    series = [{"id": "s{0}".format(index), "title": title, "edition": None, "search_titles": [],
               "confidence": 0.97, "reason": "测试"}
              for index, title in enumerate(sorted({title for _, title in titles if title}))]
    ids = {entry["title"]: entry["id"] for entry in series}
    files = [{"name": name, "series": ids[title], "unit": "volume", "number": 1, "end": None, "label": None,
              "confidence": 0.97} for name, title in titles if title]
    return {"series": series, "files": files}


class LooseFilesTests(DropFixture):
    """Files dropped one by one from one folder may have nothing to do with each other."""

    def keys(self, ai, *paths):
        self.organizer(ai=ai).scan_paths(self.library.id, self.resolve(*paths).entries)
        return {item.source_path.name: item.group_key for item in self.all_items()}

    def test_different_works_are_separate_groups(self):
        a, b = self.make("迷宫饭 01.zip"), self.make("海贼王 03.zip")
        ai = FakeAi(_reading(("迷宫饭 01.zip", "迷宫饭"), ("海贼王 03.zip", "海贼王")))
        self.assertEqual(self.keys(ai, a, b), {"迷宫饭 01.zip": "迷宫饭", "海贼王 03.zip": "海贼王"})

    def test_volumes_of_one_work_stay_together(self):
        a, b = self.make("x1.zip"), self.make("x2.zip")
        ai = FakeAi(_reading(("x1.zip", "迷宫饭"), ("x2.zip", "迷宫饭")))
        self.assertEqual(set(self.keys(ai, a, b).values()), {"迷宫饭"})

    def test_a_file_the_ai_could_not_place_stands_alone(self):
        a, b = self.make("x1.zip"), self.make("不明.zip")
        ai = FakeAi(_reading(("x1.zip", "迷宫饭"), ("不明.zip", None)))
        self.assertEqual(self.keys(ai, a, b), {"x1.zip": "迷宫饭", "不明.zip": "不明.zip"})

    def test_files_the_ai_only_guesses_at_stay_apart(self):
        a, b = self.make("IMG_1.zip"), self.make("IMG_2.zip")
        reading = _reading(("IMG_1.zip", "未知作品"), ("IMG_2.zip", "未知作品"))
        reading["series"][0]["confidence"] = 0.05
        self.assertEqual(self.keys(FakeAi(reading), a, b), {"IMG_1.zip": "IMG_1.zip", "IMG_2.zip": "IMG_2.zip"})

    def test_a_dropped_folder_stays_grouped_by_folder(self):
        self.make("某系列/1.zip")
        self.make("某系列/2.zip")
        ai = FakeAi(_reading(("1.zip", "甲"), ("2.zip", "乙")))
        self.assertEqual(set(self.keys(ai, self.drops / "某系列").values()), {"某系列"})

    def test_same_folder_name_in_two_places_both_get_an_answer(self):
        a, b = self.make("一/迷宫饭/Vol.01.zip"), self.make("二/迷宫饭/Vol.01.zip")
        self.organizer().scan_paths(self.library.id, self.resolve(a.parent, b.parent).entries)
        problems = [item.error for item in self.all_items() if item.error and "AI 没有识别" in item.error]
        self.assertEqual(len(self.all_items()), 2)
        self.assertEqual(problems, [])
        self.assertEqual(len(self.ai.requests) >= 2, True)
