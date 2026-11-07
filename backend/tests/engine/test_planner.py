from decimal import Decimal
import os
from pathlib import Path
import tempfile
import unittest

from shutong.engine.kinds.base import ParseResult, SourceEntry
from shutong.engine.kinds.manga.volume import VolumeRef
from shutong.engine.kinds.novel.naming import NovelVolume
from shutong.engine.planner import PlanInput, plan_batch
from shutong.engine.recognition import Directives, Recognition
from shutong.engine.states import ReviewReason
from shutong.engine.template import DEFAULT_TEMPLATE
from shutong.metadata.base import Subject

SUBJECT = Subject(subject_id=133315, name="ダンジョン飯", name_cn="迷宫饭", summary="简介", release_date="2014-02-15",
                  writers=("九井谅子",), publisher="KADOKAWA", genres=("漫画",), completed=True, total_volumes=14,
                  platform="漫画")


def recognition(title, volume, *, edition=None, directives=None, details=None):
    return Recognition(ParseResult(title, edition, volume, details or {}), directives or Directives())


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.lib = self.root / "library"
        self.lib.mkdir()
        self.next_id = 0

    def item(self, name, rec, *, folder=None, suffix=".cbz", subject=SUBJECT):
        self.next_id += 1
        path = self.root / "source" / (folder or "") / name
        return PlanInput(self.next_id, SourceEntry(path, "archive" if suffix != ".epub" else "epub", folder),
                         rec, subject, suffix)

    def plan(self, kind, inputs):
        return plan_batch(kind, self.lib, DEFAULT_TEMPLATE, inputs)

    def test_manga_default_target_and_metadata(self):
        [decision] = self.plan("manga", [self.item("Vol.01.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(1)),
                                                                             edition="bili电子版"))])
        self.assertEqual(decision.status, "planned")
        self.assertEqual(decision.series_name, "迷宫饭[bili电子版]")
        self.assertEqual(decision.target, Path("迷宫饭[bili电子版]/迷宫饭[bili电子版] Vol.01.cbz"))
        self.assertEqual((decision.metadata["series_name"], decision.metadata["subject_id"], decision.metadata["volume"]),
                         ("迷宫饭[bili电子版]", 133315, "volume:1"))
        self.assertEqual(decision.volume_key, "volume:1")

    def test_without_edition_in_names(self):
        rec = recognition("迷宫饭", VolumeRef.volume(Decimal(1)), edition="东立电子版")
        [decision] = plan_batch("manga", self.lib, DEFAULT_TEMPLATE, [self.item("Vol.01.zip", rec)],
                                include_edition=False)
        self.assertEqual((decision.status, decision.series_name), ("planned", "迷宫饭"))
        self.assertEqual(decision.target, Path("迷宫饭/迷宫饭 Vol.01.cbz"))
        self.assertEqual(decision.metadata["series_name"], "迷宫饭")
        self.assertEqual(decision.fields["edition"], "东立电子版")

    def test_without_edition_two_editions_of_one_volume_conflict(self):
        decisions = plan_batch("manga", self.lib, DEFAULT_TEMPLATE, [
            self.item("a.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(3)), edition="东立电子版")),
            self.item("b.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(3)), edition="bili电子版")),
        ], include_edition=False)
        self.assertEqual([(d.status, d.review_reason) for d in decisions],
                         [("planned", None), ("review", ReviewReason.CONFLICT)])

    def test_novel_without_edition_in_names(self):
        rec = recognition("魔女与使魔", NovelVolume.volume(Decimal(1)), edition="bili电子版")
        [decision] = plan_batch("novel", self.lib, DEFAULT_TEMPLATE,
                                [self.item("1.epub", rec, suffix=".epub")], include_edition=False)
        self.assertEqual(decision.series_name, "魔女与使魔")
        self.assertNotIn("bili", decision.target.as_posix())

    def source_file(self, name, size=10, mtime=None):
        path = self.root / "source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return name

    def library_file(self, relative, size=10, mtime=None):
        path = self.lib / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"y" * size)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def replan(self, name, overwrite, **options):
        rec = recognition("迷宫饭", VolumeRef.volume(Decimal(1)))
        [decision] = plan_batch("manga", self.lib, DEFAULT_TEMPLATE, [self.item(name, rec)], overwrite=overwrite, **options)
        return decision

    def test_never_overwrite_keeps_the_library_file(self):
        self.library_file("迷宫饭/迷宫饭 Vol.01.cbz")
        decision = self.replan(self.source_file("a.zip", 100), "never")
        self.assertEqual((decision.status, decision.replaces), ("duplicate", None))

    def test_always_overwrite(self):
        self.library_file("迷宫饭/迷宫饭 Vol.01.cbz", 100)
        decision = self.replan(self.source_file("a.zip", 1), "always")
        self.assertEqual((decision.status, decision.replaces), ("planned", Path("迷宫饭/迷宫饭 Vol.01.cbz")))
        self.assertEqual(decision.target, Path("迷宫饭/迷宫饭 Vol.01.cbz"))

    def test_overwrite_finds_the_volume_under_another_spelling(self):
        self.library_file("迷宫饭/旧名字 Vol.01.cbz")
        decision = self.replan(self.source_file("a.zip"), "always")
        self.assertEqual((decision.status, decision.target, decision.replaces),
                         ("planned", Path("迷宫饭/迷宫饭 Vol.01.cbz"), Path("迷宫饭/旧名字 Vol.01.cbz")))

    def test_the_larger_file_stays(self):
        self.library_file("迷宫饭/迷宫饭 Vol.01.cbz", 50)
        bigger = self.replan(self.source_file("big.zip", 51), "larger")
        self.assertEqual((bigger.status, bigger.replaces), ("planned", Path("迷宫饭/迷宫饭 Vol.01.cbz")))
        same = self.replan(self.source_file("same.zip", 50), "larger")
        self.assertEqual((same.status, same.replaces, same.note), ("duplicate", None, "库里的文件不比它小，保留库里的"))

    def test_the_newest_file_stays(self):
        self.library_file("迷宫饭/迷宫饭 Vol.01.cbz", mtime=2000)
        newer = self.replan(self.source_file("new.zip", mtime=3000), "newer")
        self.assertEqual((newer.status, newer.replaces), ("planned", Path("迷宫饭/迷宫饭 Vol.01.cbz")))
        older = self.replan(self.source_file("old.zip", mtime=1000), "newer")
        self.assertEqual((older.status, older.note), ("duplicate", "库里的文件不比它旧，保留库里的"))

    def test_newest_compares_with_the_source_the_library_file_came_from(self):
        # A library file is as old as its publishing; what counts is how old its source was.
        self.library_file("迷宫饭/迷宫饭 Vol.01.cbz", mtime=9000)
        decision = self.replan(self.source_file("new.zip", mtime=3000), "newer", source_time=lambda target: 2000.0)
        self.assertEqual(decision.status, "planned")
        self.assertEqual(decision.source_mtime, 3000.0)

    def test_an_item_never_overwrites_its_own_file(self):
        self.library_file("迷宫饭/迷宫饭 Vol.01.cbz")
        decision = self.replan(self.source_file("a.zip"), "always", owner_of=lambda target: self.next_id)
        self.assertIsNone(decision.replaces)

    def test_original_file_names(self):
        rec = recognition("迷宫饭", VolumeRef.volume(Decimal(1)))
        [decision] = plan_batch("manga", self.lib, DEFAULT_TEMPLATE, [self.item("[扫图组]迷宫饭 第1卷.zip", rec)], rename=False)
        self.assertEqual((decision.status, decision.target), ("planned", Path("迷宫饭/[扫图组]迷宫饭 第1卷.cbz")))
        self.assertEqual(decision.metadata["series_name"], "迷宫饭")
        self.assertEqual(decision.volume_key, "volume:1")

    def test_original_names_of_a_novel_keep_their_stem(self):
        rec = recognition("魔女之旅", NovelVolume.volume(Decimal(2)))
        [decision] = plan_batch("novel", self.lib, DEFAULT_TEMPLATE, [self.item("[白石定规].魔女之旅 02.epub", rec, suffix=".epub")],
                                rename=False)
        self.assertEqual(decision.target, Path("魔女之旅/[白石定规].魔女之旅 02.epub"))

    def test_a_volume_under_its_original_name_is_known_from_the_records(self):
        self.library_file("迷宫饭/第一卷.cbz")
        rec = recognition("迷宫饭", VolumeRef.volume(Decimal(1)))
        known = {("迷宫饭", "volume:1"): Path("迷宫饭/第一卷.cbz")}
        [kept] = plan_batch("manga", self.lib, DEFAULT_TEMPLATE, [self.item("第1卷.zip", rec)], rename=False, published=known)
        self.assertEqual(kept.status, "duplicate")
        [replaced] = plan_batch("manga", self.lib, DEFAULT_TEMPLATE, [self.item("第1卷.zip", rec)], rename=False,
                                published=known, overwrite="always")
        self.assertEqual((replaced.status, replaced.replaces), ("planned", Path("迷宫饭/第一卷.cbz")))

    def test_a_record_of_a_file_that_is_gone_does_not_count(self):
        rec = recognition("迷宫饭", VolumeRef.volume(Decimal(1)))
        [decision] = plan_batch("manga", self.lib, DEFAULT_TEMPLATE, [self.item("a.zip", rec)],
                                published={("迷宫饭", "volume:1"): Path("迷宫饭/第一卷.cbz")})
        self.assertEqual(decision.status, "planned")

    def test_chapter_target_uses_four_digits(self):
        [decision] = self.plan("manga", [self.item("0002 01.zip", recognition("大王饶命", VolumeRef.chapter(Decimal(2))))])
        self.assertEqual((decision.status, decision.target), ("planned", Path("大王饶命/大王饶命 Ch.0002.cbz")))
        self.assertEqual((decision.volume_key, decision.metadata["volume"], decision.metadata["title"]),
                         ("chapter:2", "chapter:2", "Ch.0002"))

    def test_chapter_and_volume_same_number_do_not_collide(self):
        decisions = self.plan("manga", [
            self.item("Vol.01.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(1)))),
            self.item("第1话.zip", recognition("迷宫饭", VolumeRef.chapter(Decimal(1)))),
        ])
        self.assertEqual([d.status for d in decisions], ["planned", "planned"])

    def test_existing_chapter_is_duplicate(self):
        (self.lib / "大王饶命").mkdir()
        (self.lib / "大王饶命" / "大王饶命 Ch.0002.cbz").write_bytes(b"x")
        [decision] = self.plan("manga", [self.item("a.zip", recognition("大王饶命", VolumeRef.chapter(Decimal(2))))])
        self.assertEqual(decision.status, "duplicate")

    def test_chapter_range_names_both_ends(self):
        [decision] = self.plan("manga", [self.item("Ch.0001.zip", recognition(
            "仙王的日常生活", VolumeRef.chapter(Decimal(1), Decimal(40))))])
        self.assertEqual((decision.status, decision.target.name), ("planned", "仙王的日常生活 Ch.0001-0040.cbz"))

    def test_existing_chapter_range_is_duplicate(self):
        (self.lib / "仙王的日常生活").mkdir()
        (self.lib / "仙王的日常生活" / "仙王的日常生活 Ch.0001-0040.cbz").write_bytes(b"x")
        [decision] = self.plan("manga", [self.item("a.zip", recognition(
            "仙王的日常生活", VolumeRef.chapter(Decimal(1), Decimal(40))))])
        self.assertEqual(decision.status, "duplicate")

    def test_width_directive(self):
        rec = recognition("迷宫饭", VolumeRef.volume(Decimal(1)), directives=Directives(width=3))
        [decision] = self.plan("manga", [self.item("Vol.01.zip", rec)])
        self.assertEqual(decision.target.name, "迷宫饭 Vol.001.cbz")

    def test_width_follows_the_series_files_in_the_library(self):
        (self.lib / "迷宫饭").mkdir()
        (self.lib / "迷宫饭" / "迷宫饭 Vol.001.cbz").write_bytes(b"x")
        (self.lib / "迷宫饭" / "迷宫饭 Ch.002.cbz").write_bytes(b"x")
        decisions = self.plan("manga", [self.item("a.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(2)))),
                                        self.item("b.zip", recognition("迷宫饭", VolumeRef.chapter(Decimal(3)))),
                                        self.item("c.zip", recognition("别的", VolumeRef.chapter(Decimal(3))))])
        self.assertEqual([d.target.name for d in decisions],
                         ["迷宫饭 Vol.002.cbz", "迷宫饭 Ch.003.cbz", "别的 Ch.0003.cbz"])

    def test_existing_volume_is_duplicate(self):
        (self.lib / "迷宫饭").mkdir()
        (self.lib / "迷宫饭" / "迷宫饭 Vol.01.cbz").write_bytes(b"x")
        [decision] = self.plan("manga", [self.item("vol.1.zip", recognition("迷宫饭", VolumeRef.volume(Decimal("1.0"))))])
        self.assertEqual(decision.status, "duplicate")

    def test_occupied_target_is_conflict(self):
        # A template without {volume}: the occupied name parses to no volume, so it is a conflict, not a duplicate.
        (self.lib / "迷宫饭").mkdir()
        (self.lib / "迷宫饭" / "迷宫饭.cbz").write_bytes(b"x")
        decisions = plan_batch("manga", self.lib, "{series}/{series}{ext}",
                               [self.item("v2.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(2))))])
        self.assertEqual((decisions[0].status, decisions[0].review_reason), ("review", ReviewReason.CONFLICT))
        self.assertTrue((self.lib / "迷宫饭" / "迷宫饭.cbz").read_bytes() == b"x")

    def test_same_batch_same_target_second_is_conflict(self):
        decisions = self.plan("manga", [
            self.item("a.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(3)))),
            self.item("b.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(3)))),
        ])
        self.assertEqual([(d.status, d.review_reason) for d in decisions],
                         [("planned", None), ("review", ReviewReason.CONFLICT)])

    def test_missing_volume_goes_to_review(self):
        [decision] = self.plan("manga", [self.item("x.zip", recognition("迷宫饭", None))])
        self.assertEqual((decision.status, decision.review_reason, decision.note),
                         ("review", ReviewReason.VOLUME, "认不出卷号"))

    def novel(self, name, volume, *, folder="[86]", details=None, directives=None):
        rec = recognition("86", volume, details=details or {"title": name}, directives=directives)
        return self.item(name, rec, folder=folder, suffix=".epub")

    def test_novel_specials_continue_existing_numbering(self):
        (self.lib / "86").mkdir()
        (self.lib / "86" / "86 SP01.epub").write_bytes(b"x")
        decisions = self.plan("novel", [self.novel("86 短篇集 B.epub", NovelVolume.special()),
                                        self.novel("86 短篇集 A.epub", NovelVolume.special())])
        self.assertEqual(sorted(d.target.name for d in decisions), ["86 SP02.epub", "86 SP03.epub"])
        by_name = {d.item_id: d.target.name for d in decisions}
        self.assertEqual(by_name[2], "86 SP02.epub")  # natural order of source names: A before B
        self.assertEqual(decisions[0].metadata["series_index"], "100000")

    def test_novel_duplicate_volume_in_batch(self):
        decisions = self.plan("novel", [self.novel("86 Vol.01.epub", NovelVolume.volume(Decimal(1))),
                                        self.novel("86 Vol.1 重制.epub", NovelVolume.volume(Decimal(1)))])
        self.assertEqual([(d.status, d.review_reason) for d in decisions],
                         [("planned", None), ("review", ReviewReason.VOLUME)])

    def test_novel_first_volume_description_only_when_library_empty(self):
        decisions = self.plan("novel", [self.novel("86 Vol.02.epub", NovelVolume.volume(Decimal(2))),
                                        self.novel("86 Vol.01.epub", NovelVolume.volume(Decimal(1)))])
        described = {d.target.name: d.metadata["description"] for d in decisions}
        self.assertEqual(described, {"86 Vol.02.epub": "", "86 Vol.01.epub": "简介"})
        (self.lib / "86").mkdir(exist_ok=True)
        (self.lib / "86" / "86 Vol.01.epub").write_bytes(b"x")
        [decision] = self.plan("novel", [self.novel("86 Vol.03.epub", NovelVolume.volume(Decimal(3)))])
        self.assertEqual(decision.metadata["description"], "")

    def test_novel_existing_volume_is_duplicate(self):
        (self.lib / "86").mkdir()
        (self.lib / "86" / "86 Vol.07.5.epub").write_bytes(b"x")
        [decision] = self.plan("novel", [self.novel("x.epub", NovelVolume.volume(Decimal("7.50")))])
        self.assertEqual(decision.status, "duplicate")

    def test_flat_template_other_series_same_volume_is_not_duplicate(self):
        (self.lib / "别的漫画 Vol.01.cbz").write_bytes(b"x")
        flat = "{series} {volume}{ext}"
        [decision] = plan_batch("manga", self.lib, flat,
                                [self.item("v1.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(1))))])
        self.assertEqual((decision.status, decision.target), ("planned", Path("迷宫饭 Vol.01.cbz")))
        (self.lib / "迷宫饭 Vol.02.cbz").write_bytes(b"x")
        [decision] = plan_batch("manga", self.lib, flat,
                                [self.item("v2.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(2))))])
        self.assertEqual(decision.status, "duplicate")

    def _cbz(self, path, series, volume):
        import zipfile
        from shutong.engine.kinds.manga.comicinfo import ComicMetadata, build_comic_info
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("001.jpg", b"\xff\xd8\xffx")
            archive.writestr("ComicInfo.xml", build_comic_info(ComicMetadata(series_name=series, volume=volume), 1))

    def test_existing_target_with_matching_metadata_is_claimed(self):
        self._cbz(self.lib / "迷宫饭" / "迷宫饭 Vol.01.cbz", "迷宫饭", VolumeRef.volume(Decimal(1)))
        [decision] = self.plan("manga", [self.item("v1.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(1))))])
        self.assertEqual((decision.status, decision.target), ("claimed", Path("迷宫饭/迷宫饭 Vol.01.cbz")))
        self.assertEqual(decision.metadata["series_name"], "迷宫饭")

    def test_without_edition_existing_volume_of_another_batch_is_conflict(self):
        self._cbz(self.lib / "迷宫饭" / "迷宫饭 Vol.03.cbz", "迷宫饭", VolumeRef.volume(Decimal(3)))
        rec = recognition("迷宫饭", VolumeRef.volume(Decimal(3)), edition="bili电子版")
        [decision] = plan_batch("manga", self.lib, DEFAULT_TEMPLATE, [self.item("v3.zip", rec)],
                                include_edition=False)
        self.assertEqual((decision.status, decision.review_reason), ("review", ReviewReason.CONFLICT))

    def test_existing_novel_target_with_matching_metadata_is_claimed(self):
        from .novel.test_epub import build_epub
        target = self.lib / "86" / "86 Vol.02.epub"
        target.parent.mkdir(parents=True)
        build_epub(target, series="86", series_index="2")
        [decision] = self.plan("novel", [self.novel("86 Vol.02.epub", NovelVolume.volume(Decimal(2)))])
        self.assertEqual(decision.status, "claimed")

    def test_existing_target_with_other_series_is_not_claimed(self):
        self._cbz(self.lib / "迷宫饭" / "迷宫饭 Vol.01.cbz", "别的漫画", VolumeRef.volume(Decimal(1)))
        [decision] = self.plan("manga", [self.item("v1.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(1))))])
        self.assertEqual(decision.status, "duplicate")
        self._cbz(self.lib / "迷宫饭" / "迷宫饭 Vol.02.cbz", "迷宫饭", VolumeRef.volume(Decimal(3)))
        [decision] = self.plan("manga", [self.item("v2.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(2))))])
        self.assertEqual(decision.status, "duplicate")

    def test_file_published_from_another_source_is_not_claimed(self):
        self._cbz(self.lib / "迷宫饭" / "迷宫饭 Vol.01.cbz", "迷宫饭", VolumeRef.volume(Decimal(1)))
        owners = []
        item = self.item("v1.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(1))))
        [decision] = plan_batch("manga", self.lib, DEFAULT_TEMPLATE, [item],
                                owner_of=lambda target: owners.append(target) or item.item_id + 1)
        self.assertEqual((decision.status, owners), ("duplicate", [Path("迷宫饭/迷宫饭 Vol.01.cbz")]))

    def test_file_published_from_this_source_is_claimed_again(self):
        self._cbz(self.lib / "迷宫饭" / "迷宫饭 Vol.01.cbz", "迷宫饭", VolumeRef.volume(Decimal(1)))
        item = self.item("v1.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(1))))
        [decision] = plan_batch("manga", self.lib, DEFAULT_TEMPLATE, [item], owner_of=lambda target: item.item_id)
        self.assertEqual(decision.status, "claimed")

    def test_unreadable_existing_target_is_not_claimed(self):
        (self.lib / "迷宫饭").mkdir()
        (self.lib / "迷宫饭" / "迷宫饭 Vol.01.cbz").write_bytes(b"not a zip")
        [decision] = self.plan("manga", [self.item("v1.zip", recognition("迷宫饭", VolumeRef.volume(Decimal(1))))])
        self.assertEqual(decision.status, "duplicate")

    def test_reuses_existing_series_directory_spelling(self):
        existing = "无职转生～到了异世界就拿出真本事～[角川电子版]"
        (self.lib / existing).mkdir()
        rec = recognition("无职转生 ～到了异世界就拿出真本事～", VolumeRef.volume(Decimal(24)), edition="角川电子版")
        [decision] = self.plan("manga", [self.item("v24.zip", rec)])
        self.assertEqual(decision.series_name, existing)
        self.assertEqual(decision.target, Path(existing) / (existing + " Vol.24.cbz"))
        self.assertEqual(decision.metadata["series_name"], existing)

    def test_does_not_reuse_directory_with_other_edition(self):
        (self.lib / "旋风管家[尖端电子版]").mkdir()
        [decision] = self.plan("manga", [self.item("v1.zip", recognition("旋风管家", VolumeRef.volume(Decimal(1))))])
        self.assertEqual(decision.series_name, "旋风管家")

    def test_does_not_reuse_ambiguous_directories(self):
        (self.lib / "Ａ漫画").mkdir()
        (self.lib / "a 漫画").mkdir()
        [decision] = self.plan("manga", [self.item("v1.zip", recognition("A漫画", VolumeRef.volume(Decimal(1))))])
        self.assertEqual(decision.series_name, "A漫画")

if __name__ == "__main__":
    unittest.main()
