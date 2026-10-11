"""Read and validate the small subset of GitHub release data we need."""

from dataclasses import asdict, dataclass
from datetime import datetime
from http.client import HTTPException
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE_BYTES = 2_000_000


class SourceError(Exception):
    """Safe-to-display source failure: never include tokens, URLs or response bodies."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Release:
    release_id: int
    tag: str
    name: str
    url: str
    published_at: str

    @property
    def identity(self) -> tuple[int, str]:
        return self.release_id, self.tag

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_api(cls, data: object) -> "Release":
        if not isinstance(data, dict):
            raise SourceError("Invalid release response: expected an object.")
        if type(data.get("id")) is not int or data["id"] <= 0:
            raise SourceError("Invalid release id.")
        for key in ("tag_name", "html_url", "published_at"):
            if not isinstance(data.get(key), str) or not data[key].strip() or len(data[key]) > 2048:
                raise SourceError(f"Invalid release field: {key}.")
        if data.get("draft") is not False or data.get("prerelease") is not False:
            raise SourceError("Expected a published stable release.")
        try:
            parts = urlsplit(data["html_url"])
            valid_url = (parts.scheme == "https" and parts.hostname == "github.com"
                         and parts.port in (None, 443) and not parts.username and not parts.password)
            published = datetime.fromisoformat(data["published_at"].replace("Z", "+00:00"))
            if not valid_url or published.tzinfo is None:
                raise ValueError
        except ValueError:
            raise SourceError("Invalid release URL or publication timestamp.") from None
        name = data.get("name") or data["tag_name"]
        if not isinstance(name, str) or len(name) > 2048:
            raise SourceError("Invalid release name.")
        return cls(data["id"], data["tag_name"], name, data["html_url"], data["published_at"])


class GitHubClient:
    def __init__(self, *, token=None, timeout=10, attempts=3,
                 base_url="https://api.github.com", sleep=time.sleep):
        self.token, self.timeout, self.attempts = token, timeout, attempts
        self.base_url, self.sleep = base_url.rstrip("/"), sleep
        self.opener = build_opener(NoRedirect())

    def latest(self, repository: str) -> Release:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "Sebastian-Release-Watch/1.0",
                   "X-GitHub-Api-Version": "2026-03-10"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(f"{self.base_url}/repos/{repository}/releases/latest", headers=headers)
        for attempt in range(self.attempts):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    length = response.headers.get("Content-Length", "")
                    if length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
                        raise SourceError("Release response exceeds the size limit.")
                    payload = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise SourceError("Release response exceeds the size limit.")
                try:
                    data = json.loads(payload)
                except (ValueError, UnicodeError, RecursionError):
                    raise SourceError("Release response is not valid JSON.") from None
                return Release.from_api(data)
            except HTTPError as exc:
                status = exc.code
                exc.close()
                if status in (403, 429):
                    raise SourceError(f"GitHub HTTP {status}: access denied or rate limited; retry on the next scheduled run.") from None
                if status == 404:
                    raise SourceError("GitHub HTTP 404: repository unavailable or no stable release.") from None
                if status not in (500, 502, 503, 504) or attempt == self.attempts - 1:
                    raise SourceError(f"GitHub HTTP {status}.") from None
            except (URLError, TimeoutError, OSError, HTTPException):
                if attempt == self.attempts - 1:
                    raise SourceError("GitHub network request failed or timed out.") from None
            self.sleep(2 ** attempt)
        raise SourceError("No request attempts configured.")
