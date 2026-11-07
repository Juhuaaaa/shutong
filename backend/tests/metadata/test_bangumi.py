import errno
import http.client
import io
import ssl
import json
from pathlib import Path
import socket
import tempfile
import unittest
from urllib.error import HTTPError, URLError

from shutong.metadata.bangumi import BangumiSettings, BangumiSource, normalize_subject
from shutong.metadata.base import MetadataUnavailable
from shutong.store.cache import CacheStore
from shutong.store.db import Database


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        return False

    def read(self):
        return self._body


def make_settings(root, bangumi_token="bangumi-secret"):
    return BangumiSettings(base_url="https://api.example.test/", token=bangumi_token)


def make_cache(root):
    database = Database(root / "shutong.db")
    database.migrate()
    return CacheStore(database)


class BangumiTests(unittest.TestCase):
    def test_normalize_subject_handles_null_and_mixed_infobox_values(self):
        subject = normalize_subject({
            "id": 279379,
            "name": "SPY×FAMILY",
            "name_cn": "间谍过家家",
            "date": None,
            "summary": "summary",
            "tags": [{"name": "漫画"}, None, {"name": 7}],
            "infobox": [
                {"key": "作者", "value": [{"v": "远藤达哉"}, "ignored", None]},
                {"key": "作画", "value": "远藤达哉"},
                {"key": "出版社", "value": [{"v": "集英社"}, {"bad": "x"}]},
                None,
            ],
        })

        self.assertEqual(subject.subject_id, "279379")
        self.assertEqual(subject.display_title, "间谍过家家")
        self.assertIsNone(subject.release_date)
        self.assertEqual(subject.writers, ("远藤达哉",))
        self.assertEqual(subject.publisher, "集英社")
        self.assertEqual(subject.genres, ("漫画",))

    def test_normalize_subject_reads_the_series_flag(self):
        self.assertIs(normalize_subject({"id": 20244, "name": "ベルベット・キス (1)", "series": False}).series, False)
        self.assertIs(normalize_subject({"id": 661086, "name": "ベルベット・アーミー", "series": True}).series, True)
        self.assertIsNone(normalize_subject({"id": 1, "name": "x"}).series)

    def test_normalize_subject_rejects_boolean_identifier(self):
        with self.assertRaisesRegex(ValueError, "subject id"):
            normalize_subject({"id": True, "name": "not an id"})

    def test_search_uses_required_request_boundary_and_cache(self):
        calls = []

        def open_request(request, timeout):
            calls.append((request, timeout))
            return FakeResponse({"data": [{"id": 279379, "name": "SPY×FAMILY"}]})

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = make_cache(root)
            client = BangumiSource(make_settings(root), database, opener=open_request)

            first = client.search("间谍过家家", "manga")
            second = client.search("间谍过家家", "manga")

        self.assertEqual(first, second)
        self.assertEqual(first[0].subject_id, "279379")
        self.assertEqual(len(calls), 1)
        request, timeout = calls[0]
        self.assertEqual(timeout, 60)
        self.assertEqual(request.full_url, "https://api.example.test/v0/search/subjects?limit=8")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("User-agent"), "shutong/0.1 (https://github.com/Juhuaaaa/shutong)")
        self.assertEqual(request.get_header("Authorization"), "Bearer bangumi-secret")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"keyword": "间谍过家家", "filter": {"type": [1]}},
        )

    def test_does_not_cache_invalid_search_data(self):
        responses = iter((
            {"data": [{"id": True, "name": "invalid"}]},
            {"data": [{"id": 279379, "name": "SPY×FAMILY"}]},
        ))
        attempts = []

        def open_request(request, timeout):
            attempts.append(request)
            return FakeResponse(next(responses))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = make_cache(root)
            client = BangumiSource(make_settings(root), database, opener=open_request)
            with self.assertRaisesRegex(ValueError, "subject id"):
                client.search("间谍过家家", "manga")
            subjects = client.search("间谍过家家", "manga")

        self.assertEqual(subjects[0].subject_id, "279379")
        self.assertEqual(len(attempts), 2)

    def test_get_subject_omits_authorization_without_token(self):
        calls = []

        def open_request(request, timeout):
            calls.append((request, timeout))
            return FakeResponse({"id": 279379, "name": "SPY×FAMILY"})

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = make_cache(root)
            client = BangumiSource(
                make_settings(root, bangumi_token=None), database, opener=open_request
            )
            subject = client.get(279379)

        self.assertEqual(subject.subject_id, "279379")
        self.assertIsNone(calls[0][0].get_header("Authorization"))

    def test_retries_retryable_http_and_socket_failures_at_most_three_attempts(self):
        outcomes = [
            HTTPError("https://api.example.test", 503, "busy", {}, io.BytesIO()),
            socket.timeout("timed out"),
            FakeResponse({"id": 279379, "name": "SPY×FAMILY"}),
        ]
        delays = []

        def open_request(request, timeout):
            outcome = outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = make_cache(root)
            client = BangumiSource(
                make_settings(root), database, opener=open_request, sleep=delays.append
            )
            subject = client.get(279379)

        self.assertEqual(subject.subject_id, "279379")
        self.assertEqual(delays, [1, 2])
        self.assertEqual(outcomes, [])

    def test_retries_transient_socket_oserror(self):
        outcomes = [
            socket.gaierror(socket.EAI_AGAIN, "temporary name resolution failure"),
            FakeResponse({"id": 279379, "name": "SPY×FAMILY"}),
        ]

        def open_request(request, timeout):
            outcome = outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = make_cache(root)
            client = BangumiSource(
                make_settings(root), database, opener=open_request, sleep=lambda delay: None
            )
            subject = client.get(279379)

        self.assertEqual(subject.subject_id, "279379")

    def test_retries_wrapped_transient_socket_oserror(self):
        outcomes = [
            URLError(
                socket.gaierror(
                    socket.EAI_AGAIN, "temporary name resolution failure"
                )
            ),
            URLError(socket.timeout("timed out")),
            FakeResponse({"id": 279379, "name": "SPY×FAMILY"}),
        ]

        def open_request(request, timeout):
            outcome = outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = make_cache(root)
            client = BangumiSource(
                make_settings(root), database, opener=open_request, sleep=lambda delay: None
            )
            subject = client.get(279379)

        self.assertEqual(subject.subject_id, "279379")
        self.assertEqual(outcomes, [])

    def test_rejects_nested_nonfinite_number_without_caching(self):
        responses = iter((
            b'{"data":[{"id":279379,"name":"SPY","nested":{"score":1e400}}]}',
            json.dumps(
                {"data": [{"id": 279379, "name": "SPY×FAMILY"}]},
                ensure_ascii=False,
            ).encode("utf-8"),
        ))
        attempts = []

        def open_request(request, timeout):
            attempts.append(request)
            response = FakeResponse({})
            response._body = next(responses)
            return response

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = make_cache(root)
            client = BangumiSource(make_settings(root), database, opener=open_request)
            with self.assertRaisesRegex(ValueError, "non-finite"):
                client.search("间谍过家家", "manga")
            subjects = client.search("间谍过家家", "manga")

        self.assertEqual(subjects[0].subject_id, "279379")
        self.assertEqual(len(attempts), 2)

    def test_stops_after_three_retryable_failures(self):
        attempts = []
        delays = []

        def open_request(request, timeout):
            attempts.append(request)
            raise HTTPError(
                "https://api.example.test", 503, "busy", {}, io.BytesIO()
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = make_cache(root)
            client = BangumiSource(
                make_settings(root), database, opener=open_request, sleep=delays.append
            )
            with self.assertRaises(MetadataUnavailable) as caught:
                client.get(279379)

        self.assertIsInstance(caught.exception.__cause__, HTTPError)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(delays, [1, 2])

    def test_does_not_retry_unauthorized_or_malformed_json(self):
        for first_response, expected_error in (
            (HTTPError("https://api.example.test", 401, "no", {}, io.BytesIO()), HTTPError),
            (b"not-json", ValueError),
        ):
            with self.subTest(expected_error=expected_error.__name__):
                attempts = []

                def open_request(request, timeout):
                    attempts.append(request)
                    if isinstance(first_response, BaseException):
                        raise first_response
                    response = FakeResponse({})
                    response._body = first_response
                    return response

                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    database = make_cache(root)
                    client = BangumiSource(make_settings(root), database, opener=open_request)
                    with self.assertRaises(expected_error):
                        client.get(279379)

                self.assertEqual(len(attempts), 1)

    def test_retry_exhaustion_on_network_errors_raises_metadata_unavailable(self):
        def open_request(request, timeout):
            raise URLError(socket.timeout("timed out"))

        with tempfile.TemporaryDirectory() as directory:
            client = BangumiSource(make_settings(Path(directory)), make_cache(Path(directory)),
                                   opener=open_request, sleep=lambda delay: None)
            with self.assertRaises(MetadataUnavailable):
                client.search("间谍过家家", "manga")

    def test_cache_key_format_matches_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = make_cache(Path(directory))
            cache.put("bangumi:search:manga:间谍过家家", {"data": [{"id": 7, "name": "缓存"}]}, ttl_seconds=60)
            cache.put("bangumi:subject:7", {"id": 7, "name": "缓存"}, ttl_seconds=60)

            def open_request(request, timeout):
                raise AssertionError("must be served from cache")

            client = BangumiSource(make_settings(Path(directory)), cache, opener=open_request)
            self.assertEqual(client.search(" 间谍过家家 ", "novel")[0].subject_id, "7")
            self.assertEqual(client.get(7).name, "缓存")

    def test_once_unreachable_later_requests_fail_fast_but_cache_still_answers(self):
        attempts = []

        def always_fail(request, timeout):
            attempts.append(request.full_url)
            raise URLError(OSError(errno.EADDRNOTAVAIL, "Cannot assign requested address"))

        with tempfile.TemporaryDirectory() as directory:
            cache = make_cache(Path(directory))
            cache.put("bangumi:subject:7", {"id": 7, "name": "缓存"}, ttl_seconds=60)
            now = [1000.0]
            client = BangumiSource(make_settings(Path(directory)), cache, opener=always_fail, sleep=lambda delay: None,
                                   clock=lambda: now[0])
            with self.assertLogs("shutong.bangumi", "WARNING"), self.assertRaises(MetadataUnavailable):
                client.get(279379)
            self.assertEqual(len(attempts), 3)
            with self.assertRaises(MetadataUnavailable):
                client.get(279380)
            self.assertEqual(len(attempts), 3)  # no new network attempts while marked down
            self.assertEqual(client.get(7).name, "缓存")
            now[0] += 301
            with self.assertLogs("shutong.bangumi", "WARNING"), self.assertRaises(MetadataUnavailable):
                client.get(279381)
            self.assertEqual(len(attempts), 6)  # tried again after the pause

    def test_offline_dns_ssl_and_truncated_reads_are_retried_then_unavailable(self):
        failures = [
            URLError(socket.gaierror(socket.EAI_NONAME, "nodename nor servname provided")),
            socket.gaierror(socket.EAI_NONAME, "Name or service not known"),
            URLError(ssl.SSLError("certificate verify failed")),
            http.client.IncompleteRead(b"partial"),
            # Seen in a NAS container: DNS answers with an IPv6 address the host cannot route to.
            URLError(OSError(errno.EADDRNOTAVAIL, "Cannot assign requested address")),
            URLError(OSError(errno.EHOSTUNREACH, "No route to host")),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                outcomes = [failure, FakeResponse({"id": 279379, "name": "SPY×FAMILY"})]

                def open_request(request, timeout):
                    outcome = outcomes.pop(0)
                    if isinstance(outcome, BaseException):
                        raise outcome
                    return outcome

                with tempfile.TemporaryDirectory() as directory:
                    client = BangumiSource(make_settings(Path(directory)), make_cache(Path(directory)),
                                           opener=open_request, sleep=lambda delay: None)
                    self.assertEqual(client.get(279379).subject_id, "279379")

                def always_fail(request, timeout):
                    raise failure

                with tempfile.TemporaryDirectory() as directory:
                    client = BangumiSource(make_settings(Path(directory)), make_cache(Path(directory)),
                                           opener=always_fail, sleep=lambda delay: None)
                    with self.assertLogs("shutong.bangumi", "WARNING") as logged:
                        with self.assertRaises(MetadataUnavailable):
                            client.get(279379)
                    self.assertIn("放弃", logged.output[-1])


if __name__ == "__main__":
    unittest.main()
