"""Deliver a JSON event once; persistent retry scheduling belongs to the store."""

import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .api import NoRedirect
from .config import validate_webhook


class AlertError(Exception):
    """Safe-to-display delivery error."""


class WebhookSender:
    def __init__(self, url: str, timeout: int = 10):
        self.url = validate_webhook(url)
        self.timeout = timeout
        self.opener = build_opener(NoRedirect())

    def send(self, payload: dict):
        request = Request(self.url, data=json.dumps(payload).encode("utf-8"), method="POST",
                          headers={"Content-Type": "application/json", "User-Agent": "Sebastian-Release-Watch/1.0",
                                   "Idempotency-Key": payload["event_id"]})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if not 200 <= response.status < 300:
                    raise AlertError(f"Webhook HTTP {response.status}.")
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise AlertError(f"Webhook HTTP {status}.") from None
        except (URLError, TimeoutError, OSError, HTTPException):
            raise AlertError("Webhook network request failed or timed out.") from None
