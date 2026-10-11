"""Command-line interface and safe process exit codes."""

import argparse
import logging
from pathlib import Path
import sqlite3
import sys
import time

from .alerts import WebhookSender
from .api import GitHubClient
from .config import load_config
from .demo import run_demo
from .locking import run_lock
from .monitor import run_once
from .report import write_report
from .store import Store, utc_now


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Monitor GitHub releases, keep history and deliver webhook alerts.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "report"):
        command = commands.add_parser(name, help="Check once and send due alerts" if name == "run" else "Rebuild reports without network requests")
        command.add_argument("--config", type=Path, default=Path("config.example.toml"))
    demo = commands.add_parser("demo", help="Run a fully offline scenario with a local webhook receiver")
    demo.add_argument("--output", type=Path, default=Path("demo-output"))
    args = parser.parse_args(argv)
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(level=logging.INFO, format="%(asctime)sZ %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    try:
        if args.command == "demo":
            report = run_demo(args.output.resolve())
            print(f"Demo complete. Open: {report}")
            return 0
        config = load_config(args.config)
        with run_lock(config.database), Store(config.database) as store:
            if args.command == "report":
                report = write_report(store.report_data(), config.report_directory, utc_now())
                print(f"Report: {report}")
                return 0
            client = GitHubClient(token=config.github_token, timeout=config.timeout_seconds, attempts=config.get_attempts)
            sender = WebhookSender(config.webhook_url, config.timeout_seconds) if config.webhook_url else None
            result = run_once(config, store, client, sender)
            print(f"Checked {result.checked}; changed {result.changed}; delivered {result.delivered}; pending {result.pending}.")
            print(f"Report: {config.report_directory / 'report.html'}")
            return result.exit_code
    except (ValueError, OSError, sqlite3.Error, RuntimeError):
        # Configuration paths and environment values may themselves contain secrets.
        print("Cannot complete the command. Check configuration, directory permissions, database health, "
              "and whether another run is active. Demo requires a new or empty output directory.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; committed history and queued events are retained.", file=sys.stderr)
        return 130
