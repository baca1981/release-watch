"""Validate local configuration and resolve secrets without displaying them."""

from dataclasses import dataclass, field
from pathlib import Path
import os
import re
import tomllib
from urllib.parse import urlsplit


def validate_repository(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}", value
    ):
        raise ValueError("Each repository must have the form owner/repository.")
    return value.lower()


def validate_webhook(value: str) -> str:
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise ValueError("Invalid webhook URL.") from None
    local_http = parts.scheme == "http" and parts.hostname in {"127.0.0.1", "::1", "localhost"}
    if (parts.scheme != "https" and not local_http) or not parts.hostname:
        raise ValueError("Webhook must use HTTPS (HTTP is allowed only on loopback for testing).")
    if parts.username or parts.password or parts.fragment or port == 0:
        raise ValueError("Webhook URL must not contain credentials or a fragment.")
    return value


@dataclass(frozen=True)
class Config:
    repositories: tuple[str, ...]
    database: Path
    report_directory: Path
    timeout_seconds: int = 10
    get_attempts: int = 3
    webhook_url: str | None = field(default=None, repr=False)
    github_token: str | None = field(default=None, repr=False)


def load_config(path: Path) -> Config:
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    allowed = {"repositories", "database", "report_directory", "timeout_seconds",
               "get_attempts", "webhook_url_env", "github_token_env"}
    if set(raw) - allowed:
        raise ValueError("Unknown configuration key; check config.example.toml.")
    repos = raw.get("repositories")
    if not isinstance(repos, list) or not 1 <= len(repos) <= 20:
        raise ValueError("Configure between 1 and 20 repositories.")
    repositories = tuple(dict.fromkeys(validate_repository(repo) for repo in repos))
    timeout = raw.get("timeout_seconds", 10)
    attempts = raw.get("get_attempts", 3)
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise ValueError("timeout_seconds must be an integer from 1 to 60.")
    if type(attempts) is not int or not 1 <= attempts <= 5:
        raise ValueError("get_attempts must be an integer from 1 to 5.")
    base = path.resolve().parent

    def config_path(key: str, default: str) -> Path:
        value = raw.get(key, default)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a nonempty path.")
        return (base / value).resolve()

    def secret(key: str, default: str) -> str | None:
        name = raw.get(key, default)
        if not isinstance(name, str) or (name and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)):
            raise ValueError(f"{key} must be an environment variable name or an empty string.")
        value = os.environ.get(name) if name else None
        if value and any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError(f"{key} contains invalid control characters.")
        return value or None

    webhook = secret("webhook_url_env", "RELEASE_WATCH_WEBHOOK_URL")
    return Config(repositories, config_path("database", "data/state.sqlite3"),
                  config_path("report_directory", "reports"), timeout, attempts,
                  validate_webhook(webhook) if webhook else None,
                  secret("github_token_env", "GITHUB_TOKEN"))
