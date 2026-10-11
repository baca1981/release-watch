import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from release_watch.api import Release, SourceError
from release_watch.config import load_config, validate_repository, validate_webhook
from tests.helpers import payload


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.toml"

    def load(self, extra=""):
        self.path.write_text('repositories = ["PSF/requests", "psf/requests"]\n' + extra, encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            return load_config(self.path)

    def test_paths_are_relative_to_config_and_repos_deduplicated(self):
        config = self.load()
        self.assertEqual(config.repositories, ("psf/requests",))
        self.assertEqual(config.database, (self.path.parent / "data/state.sqlite3").resolve())

    def test_unknown_keys_and_invalid_numbers_rejected(self):
        for extra in ['timeout_seconds = 0', 'get_attempts = true', 'get_attempts = 6', 'typo = "x"']:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.load(extra)

    def test_repositories_cannot_inject_path_or_query(self):
        for name in ["https://github.com/a/b", "../foo", "a/b?token=x", "a/b/c", "a/b\n"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_repository(name)

    def test_public_webhook_requires_https_and_no_embedded_credentials(self):
        for url in ["http://example.com/hook", "file:///tmp/a", "https://user:pass@example.com", "https://example.com/#fragment"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_webhook(url)
        self.assertEqual(validate_webhook("http://127.0.0.1:8000/hook"), "http://127.0.0.1:8000/hook")

    def test_secrets_are_absent_from_config_repr(self):
        self.path.write_text('repositories = ["test/repo"]', encoding="utf-8")
        with patch.dict(os.environ, {"GITHUB_TOKEN": "secret123", "RELEASE_WATCH_WEBHOOK_URL": "https://example.com/secret456"}):
            config = load_config(self.path)
        self.assertNotIn("secret123", repr(config))
        self.assertNotIn("secret456", repr(config))

    def test_release_schema_rejects_invalid_fields(self):
        for change in [{"id": True}, {"id": -1}, {"tag_name": ""}, {"draft": True},
                       {"prerelease": True}, {"published_at": "yesterday"},
                       {"published_at": "2026-01-01T12:00:00"}, {"name": ["bad"]},
                       {"html_url": "javascript:alert(1)"}, {"html_url": "https://github.com.evil.test/x"}]:
            with self.subTest(change=change), self.assertRaises(SourceError):
                Release.from_api(payload(**change))
