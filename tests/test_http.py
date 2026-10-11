from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import unittest

from release_watch.alerts import AlertError, WebhookSender
from release_watch.api import GitHubClient, MAX_RESPONSE_BYTES, SourceError
from tests.helpers import payload


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.responses = []
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                owner.requests.append({"method": self.command, "path": self.path,
                                       "headers": self.headers, "body": body})
                status, data, headers = owner.responses.pop(0)
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            do_GET = respond
            do_POST = respond

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.worker = Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.close)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.sleeps = []
        self.client = GitHubClient(base_url=self.base, attempts=3, sleep=self.sleeps.append)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)

    def queue(self, status=200, data=None, headers=None):
        if data is None:
            data = json.dumps(payload()).encode()
        self.responses.append((status, data, headers or {}))

    def test_valid_get_sends_api_headers(self):
        self.queue()
        self.assertEqual(self.client.latest("test/repo").tag, "v1.0")
        self.assertEqual(self.requests[0]["path"], "/repos/test/repo/releases/latest")
        self.assertEqual(self.requests[0]["headers"]["Accept"], "application/vnd.github+json")

    def test_transient_server_error_retries_and_recovers(self):
        self.queue(503)
        self.queue()
        self.assertEqual(self.client.latest("test/repo").release_id, 1)
        self.assertEqual(self.sleeps, [1])

    def test_retry_budget_is_bounded(self):
        for _ in range(3):
            self.queue(502)
        with self.assertRaisesRegex(SourceError, "HTTP 502"):
            self.client.latest("test/repo")
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(self.sleeps, [1, 2])

    def test_rate_limit_does_not_immediately_retry(self):
        for status in (403, 429):
            with self.subTest(status=status):
                self.queue(status)
                with self.assertRaisesRegex(SourceError, "next scheduled run"):
                    self.client.latest("test/repo")
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.sleeps, [])

    def test_missing_release_is_clear_failure(self):
        self.queue(404)
        with self.assertRaisesRegex(SourceError, "no stable release"):
            self.client.latest("test/repo")
        self.assertEqual(len(self.requests), 1)

    def test_invalid_json_does_not_escape_response_body(self):
        self.queue(data=b"secret-token: not json")
        with self.assertRaises(SourceError) as caught:
            self.client.latest("test/repo")
        self.assertNotIn("secret-token", str(caught.exception))

    def test_oversized_response_rejected(self):
        self.queue(data=b"x" * (MAX_RESPONSE_BYTES + 1))
        with self.assertRaisesRegex(SourceError, "size limit"):
            self.client.latest("test/repo")

    def test_source_redirect_is_not_followed_with_token(self):
        self.queue(302, headers={"Location": self.base + "/collect-secret"})
        self.client.token = "private-token"
        with self.assertRaisesRegex(SourceError, "HTTP 302"):
            self.client.latest("test/repo")
        self.assertEqual(len(self.requests), 1)

    def test_webhook_delivers_json_and_idempotency_key(self):
        self.queue(204, b"")
        event = {"event_id": "stable-event", "current": {"tag": "v2"}}
        WebhookSender(self.base + "/alert").send(event)
        request = self.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(json.loads(request["body"]), event)
        self.assertEqual(request["headers"]["Idempotency-Key"], "stable-event")

    def test_webhook_failure_never_leaks_secret_url_or_body(self):
        self.queue(500, b"private-body")
        with self.assertRaises(AlertError) as caught:
            WebhookSender(self.base + "/secret-token").send({"event_id": "one"})
        self.assertEqual(str(caught.exception), "Webhook HTTP 500.")
        self.assertEqual(len(self.requests), 1)

    def test_webhook_redirect_does_not_forward_event(self):
        self.queue(307, headers={"Location": self.base + "/elsewhere"})
        with self.assertRaisesRegex(AlertError, "HTTP 307"):
            WebhookSender(self.base + "/alert").send({"event_id": "one"})
        self.assertEqual(len(self.requests), 1)
