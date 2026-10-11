import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from release_watch.store import Store
from tests.helpers import NOW, LATER, release


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self.store.db.close)

    def test_baseline_and_unchanged_never_alert(self):
        self.assertEqual(self.store.observe("test/repo", release(), NOW), "baseline")
        self.assertEqual(self.store.observe("test/repo", release(), LATER), "unchanged")
        self.assertEqual(self.store.report_data()["totals"], {"checks": 2, "changes": 0, "pending": 0})

    def test_change_survives_restart_and_repeated_poll(self):
        self.store.observe("test/repo", release(), NOW)
        self.store.observe("test/repo", release(2), LATER)
        with Store(self.path) as reopened:
            reopened.observe("test/repo", release(2), LATER)
            events = reopened.due_events(LATER)
            self.assertEqual(len(events), 1)
            body = json.loads(events[0]["payload_json"])
            self.assertEqual(body["previous"]["tag"], "v1.0")
            self.assertEqual(body["current"]["tag"], "v2.0")

    def test_failed_write_rolls_back_snapshot_and_event(self):
        self.store.observe("test/repo", release(), NOW)
        self.store.db.execute("CREATE TRIGGER simulate_failure BEFORE INSERT ON checks BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.observe("test/repo", release(2), LATER)
        data = self.store.report_data()
        self.assertEqual(data["snapshots"][0]["release"]["tag"], "v1.0")
        self.assertEqual(data["totals"]["changes"], 0)

    def test_error_preserves_last_good_release(self):
        self.store.observe("test/repo", release(), NOW)
        self.store.record_error("test/repo", "GitHub unavailable", LATER)
        self.assertEqual(self.store.report_data()["snapshots"][0]["checked_at"], NOW)
        self.assertEqual(self.store.report_data()["checks"][0]["status"], "error")

    def test_metadata_edit_does_not_alert_but_tag_edit_does(self):
        self.store.observe("test/repo", release(), NOW)
        self.store.observe("test/repo", release(name="Edited notes"), LATER)
        self.assertEqual(self.store.report_data()["totals"]["changes"], 0)
        self.store.observe("test/repo", release(tag_name="v1.1"), LATER)
        self.assertEqual(self.store.report_data()["totals"]["changes"], 1)

    def test_regression_is_a_change_not_silently_ignored(self):
        for version in (1, 2, 1):
            self.store.observe("test/repo", release(version), NOW)
        self.assertEqual(self.store.report_data()["totals"]["changes"], 2)

    def test_persistent_backoff_and_delivery(self):
        self.store.observe("test/repo", release(), NOW)
        self.store.observe("test/repo", release(2), NOW)
        event = self.store.due_events(NOW)[0]
        self.store.mark_failed(event["event_id"], "Webhook HTTP 503.", NOW)
        self.assertEqual(self.store.due_events(NOW), [])
        pending = self.store.due_events(LATER)[0]
        self.assertEqual(pending["event_id"], event["event_id"])
        self.assertEqual(pending["attempts"], 1)
        self.store.mark_delivered(event["event_id"], LATER)
        self.assertEqual(self.store.due_events(LATER), [])
        self.assertEqual(self.store.report_data()["events"][0]["attempts"], 2)

    def test_reports_are_bounded_but_totals_are_complete(self):
        for _ in range(105):
            self.store.observe("test/repo", release(), NOW)
        data = self.store.report_data()
        self.assertEqual(len(data["checks"]), 100)
        self.assertEqual(data["totals"]["checks"], 105)
