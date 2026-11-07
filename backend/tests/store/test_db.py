from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from shutong.store.db import Database
from shutong.store.migrations import MIGRATIONS


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.db = Database(Path(self._directory.name) / "shutong.db")

    def test_migrate_creates_schema_and_sets_version(self):
        self.db.migrate()
        self.assertEqual(self.db.schema_version(), len(MIGRATIONS))
        with self.db.connect() as connection:
            names = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertLessEqual(
            {"libraries", "runs", "items", "item_events", "publish_journal", "settings"},
            names,
        )
        self.assertFalse({"rules", "trash"} & names)

    def test_migrate_is_idempotent(self):
        self.db.migrate()
        self.db.migrate()
        self.assertEqual(self.db.schema_version(), len(MIGRATIONS))

    def test_archive_policy_requires_archive_dir(self):
        self.db.migrate()
        with self.assertRaises(sqlite3.IntegrityError), self.db.connect() as connection:
            connection.execute(
                "INSERT INTO libraries(name, kind, source_dir, library_dir, source_policy, created_at)"
                " VALUES ('a', 'novel', '/s', '/l', 'archive', 't')"
            )

    def test_connect_rolls_back_on_error(self):
        self.db.migrate()
        with self.assertRaises(RuntimeError), self.db.connect() as connection:
            connection.execute("INSERT INTO settings VALUES ('k', 'v')")
            raise RuntimeError
        with self.db.connect() as connection:
            self.assertIsNone(connection.execute("SELECT * FROM settings").fetchone())

    def test_read_then_write_survives_a_concurrent_writer(self):
        # A deferred transaction that read first cannot upgrade after another commit (WAL
        # SQLITE_BUSY_SNAPSHOT); write transactions must take the lock up front instead.
        self.db.migrate()
        errors = []

        def writer():
            try:
                with self.db.connect() as connection:
                    connection.execute("INSERT INTO settings VALUES ('other', '1')")
            except Exception as error:
                errors.append(error)

        with self.db.connect() as connection:
            connection.execute("SELECT * FROM settings").fetchall()
            thread = threading.Thread(target=writer)
            thread.start()
            thread.join(timeout=0.5)
            connection.execute("INSERT INTO settings VALUES ('mine', '1')")
        thread.join()
        self.assertEqual(errors, [])
        with self.db.connect() as connection:
            keys = {row["key"] for row in connection.execute("SELECT key FROM settings")}
        self.assertEqual(keys, {"mine", "other"})

    def test_foreign_keys_enforced(self):
        self.db.migrate()
        with self.assertRaises(sqlite3.IntegrityError), self.db.connect() as connection:
            connection.execute(
                "INSERT INTO items(library_id, source_path, fingerprint, status, created_at, updated_at)"
                " VALUES (99, '/s/a', 'v1:x', 'discovered', 't', 't')"
            )

    def test_migration_two_adds_pdf_to_cbz_to_existing_libraries(self):
        with self.db.connect() as connection:
            for statement in MIGRATIONS[0].split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute("PRAGMA user_version = 1")
            connection.execute(
                "INSERT INTO libraries(name, kind, source_dir, library_dir, created_at)"
                " VALUES ('旧库', 'manga', '/s', '/l', 't')"
            )
        self.db.migrate()
        with self.db.connect() as connection:
            row = connection.execute("SELECT pdf_to_cbz FROM libraries").fetchone()
        self.assertEqual(row["pdf_to_cbz"], 1)

    def test_migration_five_adds_item_overrides(self):
        self.db.migrate()
        with self.db.connect() as connection:
            self.assertGreaterEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
            connection.execute("INSERT INTO libraries(name, kind, source_dir, library_dir, created_at)"
                               " VALUES ('库', 'manga', '/s', '/l', 't')")
            connection.execute("INSERT INTO items(library_id, source_path, fingerprint, status, created_at,"
                               " updated_at) VALUES (1, '/s/a.zip', 'f', 'discovered', 't', 't')")
            self.assertEqual(connection.execute("SELECT overrides FROM items").fetchone()[0], "{}")

    def _migrate_to(self, version):
        with self.db.connect() as connection:
            for script in MIGRATIONS[:version]:
                for statement in script.split(";"):
                    if statement.strip():
                        connection.execute(statement)
            connection.execute("PRAGMA user_version = {0}".format(version))

    def test_migration_seven_drops_the_ai_daily_limit(self):
        self._migrate_to(6)
        with self.db.connect() as connection:
            connection.execute("INSERT INTO settings(key, value) VALUES ('ai.daily_limit', '50')")
            connection.execute("INSERT INTO settings(key, value) VALUES ('ai.threshold', '0.9')")
        self.db.migrate()
        with self.db.connect() as connection:
            keys = [row[0] for row in connection.execute("SELECT key FROM settings")]
        self.assertEqual(keys, ["ai.threshold"])

    def test_migration_eight_drops_rules_trash_and_their_settings(self):
        self._migrate_to(7)
        with self.db.connect() as connection:
            connection.executemany("INSERT INTO settings(key, value) VALUES (?, ?)", [
                ("ai.enabled", "true"), ("ai.auto_adopt", "true"), ("organize.auto_execute", "true"),
                ("trash.retention_days", "30"), ("ai.threshold", "0.95"), ("ai.model", '"m"')])
        self.db.migrate()
        with self.db.connect() as connection:
            settings = dict(connection.execute("SELECT key, value FROM settings").fetchall())
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(settings, {"ai.threshold": "0.85", "ai.model": '"m"'})
        self.assertFalse({"rules", "trash"} & tables)

    def test_migration_twelve_allows_komga_and_keeps_library_links_as_text(self):
        self._migrate_to(11)
        with self.db.connect() as connection:
            connection.execute("INSERT INTO media_servers(id, kind, name, base_url, created_at)"
                               " VALUES (5, 'kavita', '家里', 'http://k', 't')")
            connection.execute("INSERT INTO libraries(id, name, kind, source_dir, library_dir, created_at, server_id,"
                               " server_library_id) VALUES (1, '漫画', 'manga', '/s', '/l', 't', 5, 3)")
        self.db.migrate()
        with self.db.connect() as connection:
            row = connection.execute("SELECT server_id, server_library_id, typeof(server_library_id) FROM libraries").fetchone()
            connection.execute("INSERT INTO media_servers(kind, name, base_url, created_at)"
                               " VALUES ('komga', 'Komga', 'http://g', 't')")
            connection.execute("UPDATE libraries SET server_library_id = '0S5E73NR0E2MP'")
            kept = connection.execute("SELECT server_library_id FROM libraries").fetchone()[0]
            problems = connection.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(tuple(row), (5, "3", "text"))
        self.assertEqual(kept, "0S5E73NR0E2MP")
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
