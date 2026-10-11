# Verification record

Verified locally on **11 October 2026**, Windows, **Python 3.14.6**.
This file records completed checks, not a claim of production deployment.

| Evidence | Result | Scope |
| --- | --- | --- |
| Automated suite | 35 tests passed | Offline, temporary SQLite databases and loopback HTTP |
| Package installation | Built and installed successfully in a separate virtual environment | No application runtime dependencies |
| Installed CLI | Help and complete demo succeeded from outside the source directory | Confirms package imports and entry point |
| Offline demo | 4 observations, 1 change, 1 delivered event, 2 delivery attempts | Synthetic release data; real local HTTP |
| Live public API | Two runs against two repositories; 4 successful observations | Read-only, no authentication or external webhook |
| HTML report | Opened and inspected in Chromium at 1440 px and 390 px | No page errors; tables scroll within mobile layout |
| CI configuration | Included Windows/Linux, Python 3.11/3.14 workflow | Remote workflow has not been executed |

## Automated tests

Run from the project directory:

```console
python -m unittest discover -s tests -v
```

Coverage includes first-run behavior, unchanged observations, restart persistence,
rollback of both snapshot and event after an injected database write failure,
preservation of good data after source failure, release regressions, persistent
retry scheduling, delivery acknowledgements, bounded reports, malformed source
responses, HTTP 5xx retry limits, HTTP 403/429, 404, oversized responses, blocked
redirects, safe error text, webhook payload/header delivery, configuration validation,
HTML escaping, process locking and complete demo recovery.

## Live API observation

Source requests used GitHub's documented
[latest release endpoint](https://docs.github.com/en/rest/releases/releases#get-the-latest-release).

| Repository | Observed tag | First observation (UTC) | Second observation (UTC) |
| --- | --- | --- | --- |
| `psf/requests` | `v2.34.2` | 2026-10-11 15:41:17 | 2026-10-11 15:41:50 |
| `pallets/flask` | `3.1.3` | 2026-10-11 15:41:17 | 2026-10-11 15:41:51 |

First run: two baselines. Second run: two unchanged observations, no change events.
These are point-in-time observations, not a promise that the versions are still current.
The saved [live report JSON](../examples/live/report.json) contains the observed
release IDs, publication timestamps and check history.

## Alert proof

The [demo HTTP receipts](../examples/demo/webhook-receipts.json) contain two POST
requests with the same event ID and idempotency key. The local receiver rejected
the first with 503 and acknowledged the second with 204. The
[pending report](../examples/demo/report-before-retry.html) and
[completed report](../examples/demo/report.html) show both stages.

The demo advances an injected clock rather than sleeping. This proves retry
eligibility and state persistence without waiting for an OS schedule.

## Boundaries

- No public repository was created or published; the project has a local Git repository.
- No persistent process or OS scheduled task was installed.
- No external webhook, email, Slack, Discord or Telegram message was sent.
- Live API proof covers baseline and unchanged reads. Change/retry proof uses the
  controlled local HTTP scenario.
- Linux and Python 3.11 execution are specified in CI but not locally verified.
- Chromium/Playwright were used only for report QA; they are not project dependencies.
