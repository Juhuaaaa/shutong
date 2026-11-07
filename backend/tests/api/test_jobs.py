import threading
import time
import unittest

from starlette.websockets import WebSocketDisconnect

from shutong.api.jobs import JobRunner
from shutong.engine.organizer import LibraryUnavailable

from .helpers import ApiCase


def wait(runner, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = runner.get(job_id)
        if job.state in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.01)
    raise AssertionError("job {0} did not finish".format(job_id))


class JobRunnerTests(unittest.TestCase):
    def setUp(self):
        self.runner = JobRunner()
        self.addCleanup(self.runner.stop)

    def test_jobs_run_in_order(self):
        order = []
        first = self.runner.submit("scan", lambda: order.append(1) or {"n": 1})
        second = self.runner.submit("scan", lambda: order.append(2) or {"n": 2})
        self.assertEqual(wait(self.runner, second.id).result, {"n": 2})
        self.assertEqual((wait(self.runner, first.id).state, order), ("done", [1, 2]))

    def test_failure_does_not_stop_the_queue(self):
        def boom():
            raise RuntimeError("坏了")

        failed = self.runner.submit("scan", boom)
        after = self.runner.submit("scan", lambda: {})
        self.assertEqual(wait(self.runner, after.id).state, "done")
        failed = wait(self.runner, failed.id)
        self.assertEqual((failed.state, failed.error), ("failed", "任务失败：RuntimeError: 坏了"))

    def test_library_unavailable_message(self):
        def offline():
            raise LibraryUnavailable("source directory of 漫画 is not available: /x")

        job = wait(self.runner, self.runner.submit("scan", offline).id)
        self.assertTrue(job.error.startswith("库目录不可用："))

    def test_subscribers_see_running_and_done(self):
        queue = self.runner.subscribe()
        gate = threading.Event()
        job = self.runner.submit("scan", lambda: gate.wait(5) and {})
        gate.set()
        wait(self.runner, job.id)
        states = []
        while not queue.empty():
            message = queue.get_nowait()
            if message["job"]["id"] == job.id:
                states.append(message["job"]["state"])
        self.assertEqual(states, ["queued", "running", "done"])

    def test_progress_is_kept_on_the_job_and_pushed_without_flooding(self):
        queue = self.runner.subscribe()

        def scan():
            for done in range(1, 4):
                self.runner.report({"done": done, "total": 3, "current": "迷宫饭"})
            return {}

        job = wait(self.runner, self.runner.submit("scan", scan).id)
        self.assertEqual(job.progress, {"done": 3, "total": 3, "current": "迷宫饭"})
        pushed = []
        while not queue.empty():
            message = queue.get_nowait()["job"]
            if message["state"] == "running" and message["progress"]:
                pushed.append(message["progress"]["done"])
        self.assertEqual(pushed, [1, 3])  # the first and the last; the ones in between within a second are skipped

    def test_cancelling_a_queued_job_keeps_it_from_running(self):
        release = threading.Event()
        self.addCleanup(release.set)
        ran = []
        self.runner.submit("scan", lambda: release.wait(5) and {})
        queued = self.runner.submit("scan", lambda: ran.append(1) or {})
        self.assertEqual(self.runner.cancel(queued.id).state, "cancelled")
        release.set()
        after = self.runner.submit("scan", lambda: {})
        wait(self.runner, after.id)
        self.assertEqual((ran, wait(self.runner, queued.id).state), ([], "cancelled"))

    def test_cancelling_a_running_job_asks_it_to_stop_and_keeps_its_result(self):
        started, stopped = threading.Event(), threading.Event()

        def work():
            started.set()
            while not self.runner.stop_requested():
                time.sleep(0.01)
            stopped.set()
            return {"published": 3}

        job = self.runner.submit("scan", work)
        self.assertTrue(started.wait(5))
        self.assertTrue(self.runner.cancel(job.id).cancelling)
        finished = wait(self.runner, job.id)
        self.assertTrue(stopped.is_set())
        self.assertEqual((finished.state, finished.result), ("cancelled", {"published": 3}))
        self.assertFalse(self.runner.stop_requested())

    def test_cancelling_a_finished_job_changes_nothing(self):
        job = wait(self.runner, self.runner.submit("scan", lambda: {}).id)
        self.assertEqual(self.runner.cancel(job.id).state, "done")

    def test_report_outside_a_job_is_ignored(self):
        self.runner.report({"done": 1, "total": 1})

    def test_unknown_job(self):
        with self.assertRaises(KeyError):
            self.runner.get(999)


class JobRoutesTests(ApiCase):
    inline_jobs = False

    def test_job_routes(self):
        self.login()
        job = self.app.state.jobs.submit("scan", lambda: {"ok": 1})
        wait(self.app.state.jobs, job.id)
        response = self.client.get("/api/jobs/{0}".format(job.id))
        self.assertEqual((response.json()["state"], response.json()["result"]), ("done", {"ok": 1}))
        self.assertEqual(self.client.get("/api/jobs").json()[0]["id"], job.id)
        missing = self.client.get("/api/jobs/999")
        self.assertEqual((missing.status_code, missing.json()["detail"]), (404, "任务不存在"))

    def test_cancel_route(self):
        self.assertEqual(self.client.post("/api/jobs/1/cancel").status_code, 401)
        self.login()
        release = threading.Event()
        self.addCleanup(release.set)
        self.app.state.jobs.submit("scan", lambda: release.wait(5) and {})
        queued = self.app.state.jobs.submit("scan", lambda: {})
        response = self.client.post("/api/jobs/{0}/cancel".format(queued.id))
        self.assertEqual((response.status_code, response.json()["state"]), (200, "cancelled"))
        self.assertEqual(self.client.post("/api/jobs/999/cancel").status_code, 404)

    def test_websocket_requires_login(self):
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.client.websocket_connect("/api/ws") as socket:
                socket.receive_json()
        self.assertEqual(caught.exception.code, 4401)

    def test_websocket_pushes_job_updates(self):
        self.login()
        with self.client.websocket_connect("/api/ws") as socket:
            job = self.app.state.jobs.submit("scan", lambda: {})
            states = []
            while "done" not in states:
                message = socket.receive_json()
                if message["type"] == "job" and message["job"]["id"] == job.id:
                    states.append(message["job"]["state"])
        self.assertEqual(states[-2:], ["running", "done"])

    def test_concurrent_reads_while_a_job_writes(self):
        self.login()
        from shutong.store.settings import SettingsStore

        def writer():
            store = SettingsStore(self.app.state.db)
            for index in range(200):
                store.set("ai.model", "m{0}".format(index))
            return {}

        job = self.app.state.jobs.submit("scan", writer)
        for _ in range(20):
            self.assertEqual(self.client.get("/api/settings").status_code, 200)  # reads the same database
        self.assertEqual(wait(self.app.state.jobs, job.id).state, "done")


if __name__ == "__main__":
    unittest.main()
