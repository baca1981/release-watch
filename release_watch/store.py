"""SQLite snapshots, check history and a transactional alert outbox."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .api import Release


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS snapshots (
                repository TEXT PRIMARY KEY, release_json TEXT NOT NULL,
                checked_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY, repository TEXT NOT NULL,
                checked_at TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, repository TEXT NOT NULL,
                detected_at TEXT NOT NULL, payload_json TEXT NOT NULL,
                delivered_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL, last_error TEXT
            );
            CREATE INDEX IF NOT EXISTS events_pending ON events(delivered_at, next_attempt_at);
        """)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def observe(self, repository: str, release: Release, now: str) -> str:
        # Serialize read/compare/write; a crash commits both snapshot and event, or neither.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            previous = self.db.execute("SELECT release_json FROM snapshots WHERE repository=?", (repository,)).fetchone()
            old = Release(**json.loads(previous[0])) if previous else None
            status = "baseline" if old is None else "unchanged"
            if old is not None and old.identity != release.identity:
                status = "changed"
                event_id = str(uuid4())
                payload = {"schema_version": 1, "event_id": event_id, "event": "release.changed",
                           "repository": repository, "detected_at": now,
                           "previous": old.to_dict(), "current": release.to_dict()}
                self.db.execute("INSERT INTO events(event_id,repository,detected_at,payload_json,next_attempt_at) VALUES(?,?,?,?,?)",
                                (event_id, repository, now, json.dumps(payload), now))
            self.db.execute("INSERT INTO snapshots VALUES(?,?,?) ON CONFLICT(repository) DO UPDATE SET release_json=excluded.release_json, checked_at=excluded.checked_at",
                            (repository, json.dumps(release.to_dict()), now))
            self.db.execute("INSERT INTO checks(repository,checked_at,status,detail) VALUES(?,?,?,?)",
                            (repository, now, status, release.tag))
        return status

    def record_error(self, repository: str, detail: str, now: str):
        with self.db:
            self.db.execute("INSERT INTO checks(repository,checked_at,status,detail) VALUES(?,?,?,?)",
                            (repository, now, "error", detail))

    def due_events(self, now: str) -> list[dict]:
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM events WHERE delivered_at IS NULL AND next_attempt_at<=? ORDER BY detected_at, rowid LIMIT 100", (now,))]

    def mark_delivered(self, event_id: str, now: str):
        with self.db:
            self.db.execute("UPDATE events SET delivered_at=?, attempts=attempts+1,last_error=NULL WHERE event_id=?", (now, event_id))

    def mark_failed(self, event_id: str, error: str, now: str):
        with self.db:
            attempts = self.db.execute("SELECT attempts FROM events WHERE event_id=?", (event_id,)).fetchone()[0]
            delay = min(3600, 60 * 2 ** min(attempts, 6))
            next_at = (datetime.fromisoformat(now) + timedelta(seconds=delay)).isoformat(timespec="seconds")
            self.db.execute("UPDATE events SET attempts=attempts+1,next_attempt_at=?,last_error=? WHERE event_id=?", (next_at, error, event_id))

    def report_data(self) -> dict:
        snapshots = []
        for row in self.db.execute("SELECT * FROM snapshots ORDER BY repository"):
            snapshots.append({"repository": row["repository"], "checked_at": row["checked_at"],
                              "release": json.loads(row["release_json"])})
        events = []
        for row in self.db.execute("SELECT * FROM events ORDER BY detected_at DESC,rowid DESC LIMIT 100"):
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            events.append(item)
        return {"snapshots": snapshots, "events": events,
                "checks": [dict(row) for row in self.db.execute("SELECT * FROM checks ORDER BY id DESC LIMIT 100")],
                "totals": {"checks": self.db.execute("SELECT count(*) FROM checks").fetchone()[0],
                           "changes": self.db.execute("SELECT count(*) FROM events").fetchone()[0],
                           "pending": self.db.execute("SELECT count(*) FROM events WHERE delivered_at IS NULL").fetchone()[0]}}
