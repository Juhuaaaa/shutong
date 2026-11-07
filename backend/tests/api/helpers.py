"""Shared fixture for API tests: a temporary data dir, an app with inline jobs, a logged-in client."""
from pathlib import Path
import tempfile
import unittest
import zipfile

from fastapi.testclient import TestClient

from shutong.api.app import create_app
from shutong.logs import shutdown_logging
from shutong.servers.base import ServerError, ServerLibrary
from shutong.services import EngineConfig, Services

from ..engine.reader_ai import ReaderAi
from ..engine.test_match import FakeSource, subject

JPEG = b"\xff\xd8\xffsynthetic-jpeg"
PASSWORD = "correct horse"
DUNGEON = subject(133315, "迷宫饭", total=14)


class FakeServer:
    """Records what the API asks a media server to do; ``error`` makes every call fail."""

    instances = []

    def __init__(self, record, error=None):
        self.record = record
        self.error = error
        self.calls = []
        FakeServer.instances.append(self)

    def _maybe_fail(self):
        if self.error:
            raise ServerError(self.error)

    def test(self):
        self.calls.append(("test",))
        self._maybe_fail()

    def libraries(self):
        self._maybe_fail()
        return [ServerLibrary("3", "漫画"), ServerLibrary("7", "轻小说")]

    def scan_library(self, library_id):
        self.calls.append(("scan", library_id))
        self._maybe_fail()

    def refresh_series(self, library_id, series_name):
        self.calls.append(("refresh", library_id, series_name))
        self._maybe_fail()
        return True


class ApiCase(unittest.TestCase):
    inline_jobs = True

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.data_dir = self.root / "data"
        self.source = FakeSource([DUNGEON], subjects={133315: DUNGEON})
        self.ai = ReaderAi()
        self.config = EngineConfig()
        self.server_error = None
        FakeServer.instances = []
        self.app = create_app(self.data_dir, inline_jobs=self.inline_jobs, services_factory=self.services,
                              server_factory=lambda record: FakeServer(record, self.server_error))
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.app.state.jobs.stop)
        self.addCleanup(shutdown_logging, self.data_dir)

    def services(self, db):
        return Services(db, self.source, self.ai, self.config)

    def login(self):
        response = self.client.post("/api/auth/setup", json={"password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)

    def server_calls(self):
        return [call for server in FakeServer.instances for call in server.calls]

    def make_server(self, **overrides):
        body = {"kind": "kavita", "name": "家里", "base_url": "http://kavita:5000", "username": "user",
                "password": "s3cret-pw"}
        body.update(overrides)
        response = self.client.post("/api/servers", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def zip(self, relative, base=None):
        path = (base or self.root / "source") / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("01.jpg", JPEG + relative.encode())
        return path

    def make_library(self, **overrides):
        source, library = self.root / "source", self.root / "library"
        source.mkdir(exist_ok=True)
        library.mkdir(exist_ok=True)
        body = {"name": "漫画", "kind": "manga", "source_dir": str(source), "library_dir": str(library)}
        body.update(overrides)
        response = self.client.post("/api/libraries", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()
