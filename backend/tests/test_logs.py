import logging
from pathlib import Path
import tempfile
import unittest

from shutong.logs import LogBuffer, set_level, setup_logging, shutdown_logging


class LogBufferTests(unittest.TestCase):
    def setUp(self):
        self.buffer = LogBuffer(capacity=5)
        self.logger = logging.getLogger("shutong.test-buffer")
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(self.buffer)
        self.addCleanup(self.logger.removeHandler, self.buffer)

    def test_keeps_the_newest_and_numbers_them(self):
        for number in range(7):
            self.logger.info("第 %d 条", number)
        entries, last = self.buffer.since(0)
        self.assertEqual([entry["message"] for entry in entries], ["第 2 条", "第 3 条", "第 4 条", "第 5 条", "第 6 条"])
        self.assertEqual(last, 7)
        self.assertEqual(self.buffer.since(6)[0][0]["message"], "第 6 条")
        self.assertEqual(self.buffer.since(7), ([], 7))

    def test_filters_by_level_and_text(self):
        self.logger.debug("细节")
        self.logger.info("扫描完成")
        self.logger.warning("Bangumi 重试")
        self.logger.error("发布失败：迷宫饭")
        entries, _ = self.buffer.since(0, level="WARNING")
        self.assertEqual([entry["level"] for entry in entries], ["WARNING", "ERROR"])
        self.assertEqual([entry["message"] for entry in self.buffer.since(0, query="迷宫")[0]], ["发布失败：迷宫饭"])

    def test_exceptions_carry_the_traceback(self):
        try:
            raise ValueError("坏了")
        except ValueError:
            self.logger.exception("任务失败")
        [entry] = self.buffer.since(0)[0]
        self.assertIn("ValueError: 坏了", entry["message"])


class SetupTests(unittest.TestCase):
    def test_writes_a_file_and_changes_level(self):
        with tempfile.TemporaryDirectory() as directory:
            buffer = setup_logging(Path(directory), "INFO")
            self.addCleanup(shutdown_logging, Path(directory))
            logger = logging.getLogger("shutong.engine")
            logger.debug("看不到")
            logger.info("看得到")
            set_level("DEBUG")
            logger.debug("现在看得到")
            for handler in logging.getLogger("shutong").handlers:
                handler.flush()
            text = (Path(directory) / "logs" / "shutong.log").read_text(encoding="utf-8")
            self.assertIn("看得到", text)
            self.assertIn("现在看得到", text)
            self.assertNotIn("看不到\n", text.replace("现在看得到", ""))
            self.assertEqual([entry["message"] for entry in buffer.since(0)[0]][-2:], ["看得到", "现在看得到"])
            self.assertIs(setup_logging(Path(directory), "INFO"), buffer)  # one set of handlers per data dir
            set_level("INFO")
            shutdown_logging(Path(directory))  # before the directory goes (Windows keeps open files)


if __name__ == "__main__":
    unittest.main()
