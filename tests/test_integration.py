from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from release_watch.alerts import AlertError
from release_watch.api import SourceError
from release_watch.cli import main
from release_watch.config import Config
from release_watch.demo import run_demo
from release_watch.locking import run_lock
from release_watch.monitor import run_once
from release_watch.report import write_report
from release_watch.store import Store
from tests.helpers import NOW, LATER, release


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = Config(("test/repo",), self.root / "state.sqlite3", self.root / "reports")

    def test_complete_demo_uses_real_http_and_one_persisted_event(self):
        with redirect_stdout(io.StringIO()):
            report = run_demo(self.root / "demo")
        receipts = json.loads((report.parent / "webhook-receipts.json").read_text())
        self.assertEqual([r["status"] for r in receipts], [503, 204])
        self.assertEqual(receipts[0]["idempotency_key"], receipts[1]["idempotency_key"])
        data = json.loads((report.parent / "report.json").read_text())
        self.assertEqual(data["totals"], {"checks": 4, "changes": 1, "pending": 0})
        self.assertEqual(data["events"][0]["attempts"], 2)
        self.assertIn("Synthetic release data", report.read_text(encoding="utf-8"))
        self.assertIn("Pending", (report.parent / "report-before-retry.html").read_text())

    def test_demo_refuses_to_overwrite_existing_output(self):
        sentinel = self.root / "keep.txt"
        sentinel.write_text("keep")
        with self.assertRaises(ValueError):
            run_demo(self.root)
        self.assertEqual(sentinel.read_text(), "keep")

    def test_source_failure_still_drains_pending_queue(self):
        client, sender = Mock(), Mock()
        client.latest.side_effect = SourceError("GitHub unavailable")
        with Store(self.config.database) as store:
            store.observe("test/repo", release(), NOW)
            store.observe("test/repo", release(2), NOW)
            result = run_once(self.config, store, client, sender, clock=lambda: LATER)
            self.assertEqual(result.source_errors, 1)
            self.assertEqual(result.delivered, 1)
            self.assertEqual(result.exit_code, 1)
            self.assertEqual(store.report_data()["snapshots"][0]["release"]["tag"], "v2.0")

    def test_failure_in_one_repository_does_not_stop_other_repository(self):
        config = Config(("test/missing", "test/working"), self.config.database, self.config.report_directory)
        client = Mock()
        client.latest.side_effect = [SourceError("No release"), release()]
        with Store(config.database) as store:
            result = run_once(config, store, client, clock=lambda: NOW)
            self.assertEqual(result.checked, 2)
            self.assertEqual(len(store.report_data()["snapshots"]), 1)

    def test_no_webhook_leaves_event_pending(self):
        client = Mock()
        client.latest.return_value = release(2)
        with Store(self.config.database) as store:
            store.observe("test/repo", release(), NOW)
            result = run_once(self.config, store, client, clock=lambda: LATER)
            self.assertEqual(result.pending, 1)
            self.assertEqual(result.delivered, 0)
            self.assertEqual(result.exit_code, 0)

    def test_failed_webhook_returns_nonzero_and_keeps_event(self):
        client, sender = Mock(), Mock()
        client.latest.return_value = release(2)
        sender.send.side_effect = AlertError("Webhook HTTP 503.")
        with Store(self.config.database) as store:
            store.observe("test/repo", release(), NOW)
            result = run_once(self.config, store, client, sender, clock=lambda: LATER)
            self.assertEqual(result.exit_code, 1)
            self.assertEqual(result.pending, 1)
            self.assertTrue((self.config.report_directory / "report.html").exists())

    def test_report_escapes_external_text(self):
        with Store(self.config.database) as store:
            store.observe("test/repo", release(tag_name='<script>alert("x")</script>'), NOW)
            path = write_report(store.report_data(), self.config.report_directory, NOW)
        html = path.read_text(encoding="utf-8")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_lock_excludes_another_process_and_releases_after_exit(self):
        code = "from pathlib import Path; from release_watch.locking import run_lock; import sys\nwith run_lock(Path(sys.argv[1])): print('acquired')"
        command = [sys.executable, "-c", code, str(self.config.database)]
        with run_lock(self.config.database):
            blocked = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("Another run", blocked.stderr)
        allowed = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_cli_missing_config_has_safe_exit_code(self):
        with redirect_stderr(io.StringIO()) as errors:
            result = main(["run", "--config", str(self.root / "missing.toml")])
        self.assertEqual(result, 2)
        self.assertNotIn("Traceback", errors.getvalue())

    def test_cli_report_creates_empty_report_without_api_calls(self):
        config_path = self.root / "config.toml"
        config_path.write_text('repositories = ["test/repo"]', encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            result = main(["report", "--config", str(config_path)])
        self.assertEqual(result, 0)
        self.assertTrue((self.root / "reports/report.html").exists())
