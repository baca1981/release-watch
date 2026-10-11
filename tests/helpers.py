from release_watch.api import Release

NOW = "2026-01-01T12:00:00+00:00"
LATER = "2026-01-01T12:02:00+00:00"


def payload(version=1, **overrides):
    return {"id": version, "tag_name": f"v{version}.0", "name": f"Release {version}",
            "html_url": f"https://github.com/test/repo/releases/tag/v{version}.0",
            "published_at": "2026-01-01T12:00:00Z", "draft": False, "prerelease": False, **overrides}


def release(version=1, **overrides):
    return Release.from_api(payload(version, **overrides))
