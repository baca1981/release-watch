"""Offline demonstration using real HTTP on loopback and synthetic release data."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread

from .alerts import WebhookSender
from .api import GitHubClient
from .config import Config
from .monitor import run_once
from .report import atomic_write
from .store import Store


def run_demo(output: Path) -> Path:
    if output.exists() and any(output.iterdir()):
        raise ValueError("Demo output must be an empty or new directory; choose a new --output path.")
    output.mkdir(parents=True, exist_ok=True)
    scenario = {"version": 1, "posts": 0, "receipts": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path != "/repos/demo/example/releases/latest":
                self.send_error(404)
                return
            version = scenario["version"]
            payload = {"id": version, "tag_name": f"v1.{version - 1}.0", "name": "Synthetic demo release",
                       "html_url": f"https://github.com/demo/example/releases/tag/v1.{version - 1}.0",
                       "published_at": "2026-01-01T12:00:00Z", "draft": False, "prerelease": False}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            scenario["posts"] += 1
            status = 503 if scenario["posts"] == 1 else 204
            scenario["receipts"].append({"status": status,
                                         "idempotency_key": self.headers.get("Idempotency-Key"),
                                         "payload": payload})
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    config = Config(("demo/example",), output / "state.sqlite3", output)
    client = GitHubClient(base_url=base, attempts=1)
    sender = WebhookSender(base + "/alerts")
    rows = []
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    try:
        with Store(config.database) as store:
            for index, (label, version) in enumerate([
                ("1. Establish baseline", 1), ("2. Same release: no duplicate", 1),
                ("3. New release: receiver returns 503", 2),
                ("4. Retry queued alert: receiver accepts", 2),
            ]):
                scenario["version"] = version
                now = (start + timedelta(minutes=index * 2)).isoformat(timespec="seconds")
                result = run_once(config, store, client, sender, clock=lambda: now,
                                  report_note="Offline demo / Synthetic release data and scenario timestamps")
                rows.append({"step": label, **asdict(result)})
                print(f"{label} | changed={result.changed} delivered={result.delivered} pending={result.pending}")
                if index == 2:
                    atomic_write(output / "report-before-retry.html", (output / "report.html").read_text(encoding="utf-8"))
        atomic_write(output / "webhook-receipts.json", json.dumps(scenario["receipts"], indent=2) + "\n")
        atomic_write(output / "demo-results.json", json.dumps(rows, indent=2) + "\n")
        atomic_write(output / "DEMO-NOTE.txt", "Offline demo: synthetic releases, fixed scenario timestamps, real HTTP only on 127.0.0.1.\nFirst webhook attempt deliberately returns 503; second returns 204.\nNo external messages are sent.\n")
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    return output / "report.html"
