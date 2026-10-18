import pytest
from fastapi.testclient import TestClient

from app.fetcher import run_fetch
from app.main import app


@pytest.fixture
def client(cfg, db_file, feeds):
    run_fetch(cfg, db_file, feeds.client())
    with TestClient(app) as c:
        yield c


def test_topics(client):
    topics = client.get("/api/topics").json()
    assert [t["id"] for t in topics] == ["top", "politik", "tech"]


def test_articles_chronological_without_paywall(client):
    data = client.get("/api/articles?topics=politik").json()
    titles = [a["title"] for a in data["items"]]
    assert titles == ["Bundestag beschließt Haushalt 2027",
                      "Wahlrechtsreform: Was sich jetzt ändert",
                      "Nur ein Bild per http"]
    times = [a["published_at"] for a in data["items"]]
    assert times == sorted(times, reverse=True)
    assert data["next"] is None


def test_articles_multiple_topics_no_duplicates(client):
    items = client.get("/api/articles?topics=politik,tech").json()["items"]
    urls = [a["url"] for a in items]
    assert len(urls) == len(set(urls)) == 5
    haushalt = next(a for a in items if a["title"].startswith("Bundestag"))
    assert sorted(haushalt["topics"]) == ["politik", "tech"]


def test_pagination(client):
    first = client.get("/api/articles?topics=politik,tech&limit=2").json()
    assert len(first["items"]) == 2 and first["next"]
    second = client.get(f"/api/articles?topics=politik,tech&limit=2&before={first['next']}").json()
    assert {a["id"] for a in first["items"]}.isdisjoint(a["id"] for a in second["items"])


def test_invalid_topic_and_cursor(client):
    assert client.get("/api/articles?topics=gibtsnicht").status_code == 400
    assert client.get("/api/articles?topics=tech&before=abc").status_code == 400


def test_sources_status(client):
    sources = {s["id"]: s for s in client.get("/api/sources").json()}
    assert sources["kaputt"]["error_count"] == 1
    assert sources["politik-feed"]["articles"] == 5


def test_privacy_headers_and_frontend(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert "set-cookie" not in r.headers
    assert client.get("/api/health").json()["status"] == "ok"
