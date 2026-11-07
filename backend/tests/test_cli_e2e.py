import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from shutong import cli
from shutong.engine.kinds.manga.comicinfo import read_comic_info
from shutong.engine.kinds.novel.epub import read_metadata
from shutong.metadata.base import Subject
from shutong.services import EngineConfig, Services

from .engine.novel.test_epub import build_epub
from .engine.reader_ai import ReaderAi

JPEG = b"\xff\xd8\xffsynthetic-jpeg"
AI = ReaderAi(series={"[间谍过家家][东立电子版]": {"title": "间谍过家家", "edition": "东立电子版"},
                      "[86][安里アサト]": {"title": "86"}, "[间谍过家家]": {"title": "间谍过家家"}})


def subject(subject_id, name_cn, platform, total):
    return Subject(subject_id=subject_id, name="", name_cn=name_cn, summary="简介", release_date="2019-03-25",
                   writers=("作者",), publisher="出版社", genres=(platform,), completed=False,
                   total_volumes=total, platform=platform)


class FakeSource:
    name = "fake"

    def __init__(self):
        self.subjects = [subject(279379, "间谍过家家", "漫画", 12), subject(219247, "86", "小说", 13)]

    def search(self, query, kind):
        return tuple(self.subjects)

    def get(self, subject_id):
        return next(s for s in self.subjects if s.subject_id == subject_id)


class CliEndToEndTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.data = self.root / "data"
        patcher = mock.patch.object(
            cli, "services_factory",
            lambda db: Services(db, FakeSource(), AI, EngineConfig()))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--data", str(self.data), *map(str, args)])
        return code, out.getvalue()

    def test_full_flow(self):
        manga_source, manga_library = self.root / "下载" / "漫画", self.root / "库" / "漫画"
        novel_source, novel_library = self.root / "下载" / "轻小说", self.root / "库" / "轻小说"
        archive = manga_source / "[间谍过家家][东立电子版]" / "间谍过家家 Vol.01.zip"
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("01.jpg", JPEG)
        book = novel_source / "[86][安里アサト]" / "86 Vol.01.epub"
        book.parent.mkdir(parents=True)
        build_epub(book, title="第一卷")
        manga_library.mkdir(parents=True)
        novel_library.mkdir(parents=True)

        self.assertEqual(self.run_cli("library", "add", "漫画", "--kind", "manga", "--source", manga_source,
                                      "--library", manga_library)[0], 0)
        self.assertEqual(self.run_cli("library", "add", "轻小说", "--kind", "novel", "--source", novel_source,
                                      "--library", novel_library, "--policy", "archive",
                                      "--archive", self.root / "原档")[0], 0)
        self.assertIn("漫画", self.run_cli("library", "list")[1])

        code, out = self.run_cli("scan", "漫画")
        self.assertEqual(code, 0)
        self.assertIn("间谍过家家[东立电子版]/间谍过家家[东立电子版] Vol.01.cbz", out)
        self.assertEqual(self.run_cli("scan", "轻小说")[0], 0)

        self.assertEqual(self.run_cli("execute", "漫画", "--all-planned")[0], 0)
        self.assertEqual(self.run_cli("execute", "轻小说", "--all-planned")[0], 0)

        cbz = manga_library / "间谍过家家[东立电子版]" / "间谍过家家[东立电子版] Vol.01.cbz"
        fields = read_comic_info(cbz)
        self.assertEqual((fields["Series"], fields["Web"]), ("间谍过家家[东立电子版]", "https://bgm.tv/subject/279379"))
        self.assertTrue(archive.exists())  # manga library keeps sources by default
        epub = novel_library / "86" / "86 Vol.01.epub"
        self.assertEqual((read_metadata(epub).series, read_metadata(epub).title), ("86", "第一卷"))
        self.assertFalse(book.exists())
        self.assertTrue((self.root / "原档" / "[86][安里アサト]" / "86 Vol.01.epub").exists())

        code, out = self.run_cli("scan", "漫画")
        self.assertEqual(code, 0)
        self.assertIn("known 1", out)
        self.assertIn("published", self.run_cli("items", "漫画")[1])

    def test_review_exit_code_and_items_filter(self):
        source, library = self.root / "s", self.root / "l"
        (source / "无卷号").mkdir(parents=True)
        with zipfile.ZipFile(source / "无卷号" / "没有卷号.zip", "w") as handle:
            handle.writestr("01.jpg", JPEG)
        library.mkdir()
        self.run_cli("library", "add", "漫画", "--kind", "manga", "--source", source, "--library", library)
        code, out = self.run_cli("scan", "漫画")
        self.assertEqual(code, 3)
        self.assertIn("needs_review", out)
        self.assertIn("没有卷号.zip", self.run_cli("items", "漫画", "--status", "needs_review")[1])
        self.assertEqual(self.run_cli("items", "漫画", "--status", "planned")[1].strip(), "")

    def test_settings_hide_secrets_and_parse_values(self):
        self.run_cli("setting", "set", "bangumi.token", "bgm-super-secret")
        self.run_cli("setting", "set", "ai.threshold", "0.9")
        self.run_cli("setting", "set", "ai.use_proxy", "true")
        out = self.run_cli("setting", "list")[1]
        self.assertNotIn("bgm-super-secret", out)
        self.assertIn("bangumi.token = 已设置", out)
        self.assertIn("ai.threshold = 0.9", out)
        self.assertIn("ai.use_proxy = true", out)

    def test_bad_input_returns_error_code(self):
        self.assertEqual(self.run_cli("scan", "不存在的库")[0], 2)
        (self.root / "l").mkdir()
        self.run_cli("library", "add", "漫画", "--kind", "manga", "--source", self.root, "--library", self.root / "l")
        with mock.patch.object(cli, "services_factory", lambda db: Services(db, FakeSource(), None, EngineConfig())):
            out = io.StringIO()
            with contextlib.redirect_stderr(out):
                self.assertEqual(self.run_cli("scan", "漫画")[0], 2)
        self.assertIn("AI", out.getvalue())

    def test_retry_command_and_parked_exit_code(self):
        from shutong.metadata.base import MetadataUnavailable

        state = {"online": False}

        class Flaky(FakeSource):
            def search(self, query, kind):
                if not state["online"]:
                    raise MetadataUnavailable("down")
                return super().search(query, kind)

        source, library = self.root / "s", self.root / "l"
        archive = source / "[间谍过家家]" / "间谍过家家 Vol.01.zip"
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("01.jpg", JPEG)
        library.mkdir()
        with mock.patch.object(cli, "services_factory", lambda db: Services(db, Flaky(), AI, EngineConfig())):
            self.run_cli("library", "add", "漫画", "--kind", "manga", "--source", source, "--library", library)
            code, out = self.run_cli("scan", "漫画")
            self.assertEqual(code, 3)
            self.assertIn("parsed", out)
            state["online"] = True
            code, out = self.run_cli("retry", "漫画", "--all")
            self.assertEqual(code, 0)
            self.assertIn("planned", self.run_cli("items", "漫画")[1])

    def test_bad_template_rejected_at_library_add(self):
        code = self.run_cli("library", "add", "漫画", "--kind", "manga", "--source", self.root,
                            "--library", self.root / "l", "--template", "{series}/{colour}{ext}")[0]
        self.assertEqual(code, 2)
        self.assertEqual(self.run_cli("library", "list")[1].strip(), "")

    def test_unavailable_library_is_reported_not_crashed(self):
        self.run_cli("library", "add", "漫画", "--kind", "manga", "--source", self.root / "nope",
                     "--library", self.root / "l")
        self.assertEqual(self.run_cli("scan", "漫画")[0], 2)

    def test_library_set_template(self):
        self.run_cli("library", "add", "漫画", "--kind", "manga", "--source", self.root, "--library", self.root / "l")
        self.assertEqual(self.run_cli("library", "set", "漫画", "--template", "{series}/{colour}{ext}")[0], 2)
        self.assertEqual(self.run_cli("library", "set", "漫画", "--template", "{series}/{volume}{ext}")[0], 0)
        self.assertIn("{series}/{volume}{ext}", self.run_cli("library", "list")[1])
        self.assertEqual(self.run_cli("library", "set", "漫画", "--template", "")[0], 0)
        self.assertNotIn("{series}/{volume}{ext}", self.run_cli("library", "list")[1])



if __name__ == "__main__":
    unittest.main()
