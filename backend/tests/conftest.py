import os
from pathlib import Path

import hashlib
import json
import re

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


def bag_of_words(text: str, dim: int = 512) -> list[float]:
    """Deterministisches Pseudo-Embedding: gleiche Wörter -> ähnliche Vektoren."""
    v = [0.0] * dim
    for w in re.findall(r"\w{4,}", text.lower()):
        if w in ("clustering", "kurzer", "anrisstext"):
            continue
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1.0
    v[0] += 0.01  # nie Nullvektor
    return v


class FakeOllama:
    def __init__(self, models=("nomic-embed-text:latest", "llama3.1:latest"), up=True):
        self.models = models
        self.up = up
        self.chats: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if not self.up:
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in self.models]})
        body = json.loads(request.content)
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [bag_of_words(t) for t in body["input"]]})
        if request.url.path == "/api/chat":
            self.chats.append(body)
            content = {"satz": "Mehrere Medien berichten übereinstimmend über dieses Ereignis."}
            if "Themen" in body["messages"][0]["content"]:
                content = {"themen": ["sport"]}
            return httpx.Response(200, json={"message": {"content": json.dumps(content)}})
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(self.handler))


@pytest.fixture
def fake_ollama():
    return FakeOllama()
