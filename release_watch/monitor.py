"""Coordinate one bounded monitoring run; scheduling is left to the OS."""

from dataclasses import asdict, dataclass
import json
import logging

from .alerts import AlertError
from .api import SourceError
from .report import write_report
from .store import utc_now

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    checked: int = 0
    changed: int = 0
    source_errors: int = 0
    delivered: int = 0
    delivery_errors: int = 0
    pending: int = 0

    @property
    def exit_code(self) -> int:
        return 1 if self.source_errors or self.delivery_errors else 0


def run_once(config, store, client, sender=None, *, clock=utc_now, report_note="") -> RunResult:
    result = RunResult()
    for repository in config.repositories:
        result.checked += 1
        try:
            release = client.latest(repository)
        except SourceError as exc:
            store.record_error(repository, str(exc), clock())
            result.source_errors += 1
            log.warning("source_error repository=%s detail=%s", repository, exc)
        else:
            status = store.observe(repository, release, clock())
            result.changed += status == "changed"
            log.info("observation repository=%s status=%s", repository, status)

    # Deliver older pending events even when this run could not reach the source.
    if sender:
        for event in store.due_events(clock()):
            try:
                sender.send(json.loads(event["payload_json"]))
            except AlertError as exc:
                store.mark_failed(event["event_id"], str(exc), clock())
                result.delivery_errors += 1
                log.warning("delivery_failed event_id=%s detail=%s", event["event_id"], exc)
            else:
                store.mark_delivered(event["event_id"], clock())
                result.delivered += 1
                log.info("delivery_succeeded event_id=%s", event["event_id"])
    data = store.report_data()
    result.pending = data["totals"]["pending"]
    if result.pending and sender is None:
        log.warning("delivery_disabled pending=%s configure_webhook=true", result.pending)
    write_report(data, config.report_directory, clock(), note=report_note)
    log.info("run_complete %s", json.dumps(asdict(result), sort_keys=True))
    return result
