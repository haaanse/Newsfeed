import os
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
os.environ["NEWSFEED_CONFIG"] = str(FIXTURES / "test_config.yaml")
os.environ["NEWSFEED_DISABLE_SCHEDULER"] = "1"


class FakeFeeds:
    """Simuliert die Feed-Server inkl. ETag/304."""

    def __init__(self):
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/politik.xml":
            if request.headers.get("if-none-match") == '"v1"':
                return httpx.Response(304)
            return httpx.Response(200, content=(FIXTURES / "rss_politik.xml").read_bytes(),
                                  headers={"ETag": '"v1"'})
        if path == "/tech.xml":
            return httpx.Response(200, content=(FIXTURES / "atom_tech.xml").read_bytes())
        if path == "/kaputt.xml":
            return httpx.Response(500)
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def db_file(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("NEWSFEED_DB", str(path))
    from app import db
    db.init_db(path)
    return path


@pytest.fixture
def feeds():
    return FakeFeeds()


@pytest.fixture
def cfg():
    from app.config import load_config
    return load_config()
