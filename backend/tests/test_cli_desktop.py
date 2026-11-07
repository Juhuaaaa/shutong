"""The process Electron starts: one line when ready, gone when its stdin closes."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
import urllib.error
import urllib.request

from shutong.cli import _desktop_listener
from shutong.store.db import Database, SchemaTooNew
from shutong.store.migrations import MIGRATIONS

TOKEN = "secret-token-value-0123456789"


class ListenerTests(unittest.TestCase):
    def _port_in_time_wait(self):
        """A port whose server side closed a connection first, the state a quit leaves behind."""
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        client = socket.create_connection(("127.0.0.1", port))
        accepted, _ = server.accept()
        accepted.close()
        client.recv(1)
        client.close()
        server.close()
        return port

    @unittest.skipIf(os.name == "nt", "Windows has no such wait for a listening port")
    def test_keeps_the_port_right_after_a_quit(self):
        port = self._port_in_time_wait()
        listener = _desktop_listener(port)
        self.addCleanup(listener.close)
        self.assertEqual(listener.getsockname()[1], port)

    def test_moves_on_when_something_else_listens_there(self):
        other = socket.socket()
        other.bind(("127.0.0.1", 0))
        other.listen()
        self.addCleanup(other.close)
        listener = _desktop_listener(other.getsockname()[1])
        self.addCleanup(listener.close)
        self.assertNotEqual(listener.getsockname()[1], other.getsockname()[1])


class DesktopServeTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.data = Path(self._directory.name) / "data"

    def start(self, token=TOKEN, extra=()):
        env = {key: value for key, value in os.environ.items() if key != "SHUTONG_DESKTOP_TOKEN"}
        if token:
            env["SHUTONG_DESKTOP_TOKEN"] = token
        process = subprocess.Popen([sys.executable, "-m", "shutong.cli", "--data", str(self.data), "desktop-serve", *extra],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.addCleanup(process.kill)
        self.addCleanup(process.stdout.close)
        self.addCleanup(process.stderr.close)
        self.addCleanup(lambda: process.stdin.closed or process.stdin.close())
        return process

    def test_handshake_token_and_exit_on_stdin_close(self):
        process = self.start()
        line = process.stdout.readline().decode()
        self.assertTrue(line.startswith("SHUTONG_READY "), line)
        port = json.loads(line.split(" ", 1)[1])["port"]
        request = urllib.request.Request("http://127.0.0.1:{0}/api/auth/status".format(port),
                                         headers={"Cookie": "shutong_session=" + TOKEN})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertTrue(json.load(response)["logged_in"])
        with self.assertRaises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen("http://127.0.0.1:{0}/api/libraries".format(port), timeout=5)
        self.assertEqual(refused.exception.code, 401)
        process.stdin.close()
        self.assertEqual(process.wait(timeout=10), 0)
        logs = "".join(path.read_text(encoding="utf-8", errors="replace") for path in self.data.rglob("*.log"))
        self.assertNotIn(TOKEN, logs)

    def test_asked_for_port_is_used_and_a_taken_one_falls_back(self):
        import socket
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            busy = taken.getsockname()[1]
            process = self.start(extra=["--port", str(busy)])
            line = process.stdout.readline().decode()
            self.assertNotEqual(json.loads(line.split(" ", 1)[1])["port"], busy)
            process.stdin.close()
            process.wait(timeout=10)
        process = self.start(extra=["--port", str(busy)])
        line = process.stdout.readline().decode()
        self.assertEqual(json.loads(line.split(" ", 1)[1])["port"], busy)

    def test_missing_token_exits_with_usage_error(self):
        process = self.start(token=None)
        self.assertEqual(process.wait(timeout=20), 2)

    def test_newer_database_is_refused_and_left_alone(self):
        self.data.mkdir()
        db = Database(self.data / "shutong.db")
        db.migrate()
        too_new = len(MIGRATIONS) + 1
        connection = sqlite3.connect(db.path)
        connection.execute("PRAGMA user_version = {0}".format(too_new))
        connection.close()
        process = self.start()
        line = process.stdout.readline().decode()
        self.assertEqual(json.loads(line.split(" ", 1)[1])["code"], "schema_too_new")
        self.assertEqual(process.wait(timeout=20), 1)
        self.assertEqual(db.schema_version(), too_new)


class SelftestTests(unittest.TestCase):
    def test_reads_an_archive_and_says_how_many_pages(self):
        with tempfile.TemporaryDirectory() as root:
            archive = Path(root) / "迷宫饭 第1卷.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("第01页.jpg", b"\xff\xd8\xff\xe0synthetic")
            result = subprocess.run([sys.executable, "-m", "shutong.cli", "desktop-selftest", str(archive)],
                                    capture_output=True, text=True)
        self.assertEqual((result.returncode, json.loads(result.stdout)["pages"]), (0, 1), result.stderr)


class UpgradeBackupTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.db = Database(Path(self._directory.name) / "shutong.db")

    def test_backup_before_upgrade(self):
        with self.db.connect() as connection:
            for statement in MIGRATIONS[0].split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute("PRAGMA user_version = 1")
        backup = self.db.backup_before_upgrade()
        self.assertEqual(backup.name, "shutong.db.bak-v1")
        self.assertEqual(Database(backup).schema_version(), 1)

    def test_new_and_current_databases_need_no_backup(self):
        self.assertIsNone(self.db.backup_before_upgrade())
        self.db.migrate()
        self.assertIsNone(self.db.backup_before_upgrade())

    def test_too_new_raises(self):
        self.db.migrate()
        with self.db.connect() as connection:
            connection.execute("PRAGMA user_version = {0}".format(len(MIGRATIONS) + 1))
        with self.assertRaises(SchemaTooNew):
            self.db.check_compatible()
