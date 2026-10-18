import pytest
from fastapi.testclient import TestClient

from app import db, enrich, stories
from app.main import app
from app.ollama import Ollama

from .conftest import FakeOllama
from .helpers import add


@pytest.fixture
def scenario(cfg, db_file):
    with db.connect(db_file) as conn:
        ids = {
            "h1": add(conn, cfg, "politik-feed", "Beispiel", "politik",
                      "Bundestag beschließt Haushalt mit Rekordschulden", "Der Bundestag hat den Haushalt beschlossen.", 3),
            "h2": add(conn, cfg, "tech-feed", "Technik", "tech",
                      "Haushalt beschlossen: Bundestag stimmt Rekordschulden zu", "Rekordschulden im Haushalt.", 2),
            "h3": add(conn, cfg, "top-a", "Nachrichten", "top",
                      "Rekordschulden: Bundestag beschließt Haushalt", "", 1),
            "cpu": add(conn, cfg, "tech-feed", "Technik", "tech",
                       "Neuer Prozessor mit hundert Kernen vorgestellt", "Chiphersteller zeigt Prozessor.", 1),
            "s1": add(conn, cfg, "sport-feed", "SportX", "sport",
                      "Bayern gewinnt Bundesliga Spitzenspiel gegen Dortmund", "Tore Bundesliga Fußball", 5),
            "s2": add(conn, cfg, "sport-feed", "SportX", "sport",
                      "Dortmund verliert Bundesliga Spitzenspiel", "Fußball Bundesliga Tore", 6),
            "s3": add(conn, cfg, "sport-feed", "SportX", "sport",
                      "Bayern Torjäger trifft im Bundesliga Spitzenspiel", "Bundesliga Fußball Tore", 7),
            "top_sport": add(conn, cfg, "top-a", "Nachrichten", "top",
                             "Fußball Bundesliga: Bayern schlägt Dortmund im Spitzenspiel", "Tore", 4),
            "ki": add(conn, cfg, "politik-feed", "Beispiel", "politik",
                      "EU reguliert künstliche Intelligenz streng", "Neue Regeln für KI-Anbieter.", 8),
        }
    return ids


def test_topic_rules_assign_ki(scenario, db_file):
    with db.connect(db_file) as conn:
        topics = {r[0] for r in conn.execute("SELECT topic FROM article_topics WHERE article_id = ?",
                                             (scenario["ki"],))}
    assert topics == {"politik", "ki"}


def test_enrich_clusters_classifies_and_summarizes(cfg, db_file, scenario, fake_ollama):
    stats = enrich.run(cfg, db_file, Ollama(cfg, fake_ollama.client()))
    assert stats["embedded"] == 9
    with db.connect(db_file) as conn:
        cluster = {k: conn.execute("SELECT cluster_id FROM articles WHERE id = ?", (v,)).fetchone()[0]
                   for k, v in scenario.items()}
        assert cluster["h1"] == cluster["h2"] == cluster["h3"]
        assert cluster["cpu"] != cluster["h1"]
        assert cluster["ki"] != cluster["h1"]
        topics = {r[0] for r in conn.execute("SELECT topic FROM article_topics WHERE article_id = ?",
                                             (scenario["top_sport"],))}
        assert "sport" in topics
        summary = conn.execute("SELECT summary FROM clusters WHERE id = ?", (cluster["h1"],)).fetchone()[0]
        assert summary.startswith("Mehrere Medien")

    # zweiter Lauf: nichts Neues
    again = enrich.run(cfg, db_file, Ollama(cfg, fake_ollama.client()))
    assert again["embedded"] == 0 and again["clustered"] == 0


def test_story_feed_groups_and_ranks(cfg, db_file, scenario, fake_ollama):
    enrich.run(cfg, db_file, Ollama(cfg, fake_ollama.client()))
    with db.connect(db_file) as conn:
        result = stories.build(conn, cfg, stories.Query(topics=["politik", "tech"]))
    first = result["items"][0]
    assert first["title"] == "Bundestag beschließt Haushalt mit Rekordschulden"  # höchstes Quellengewicht
    assert first["source_count"] == 3
    assert {s["publisher"] for s in first["sources"]} == {"Technik", "Nachrichten"}
    assert first["overview"]
    assert result["total"] == 3   # Haushalt-Story, Prozessor, KI-Regeln
    scores = [s["score"] for s in result["items"]]
    assert scores == sorted(scores, reverse=True)


def test_without_ollama_everything_still_works(cfg, db_file, scenario):
    down = FakeOllama(up=False)
    assert "skipped" in enrich.run(cfg, db_file, Ollama(cfg, down.client()))
    with db.connect(db_file) as conn:
        result = stories.build(conn, cfg, stories.Query(topics=["politik"], sort="latest"))
    assert [s["source_count"] for s in result["items"]] == [1, 1]


def test_missing_model_is_reported(cfg, db_file, scenario):
    no_model = FakeOllama(models=("llama3.1:latest",))
    result = enrich.run(cfg, db_file, Ollama(cfg, no_model.client()))
    assert "ollama pull nomic-embed-text" in result["skipped"]


def test_feed_api(cfg, db_file, scenario, fake_ollama):
    enrich.run(cfg, db_file, Ollama(cfg, fake_ollama.client()))
    with TestClient(app) as client:
        top = client.get("/api/feed?topics=politik,tech,sport&limit=2").json()
        assert len(top["items"]) == 2 and top["next_offset"] == 2
        page2 = client.get("/api/feed?topics=politik,tech,sport&limit=2&offset=2").json()
        assert {s["id"] for s in top["items"]}.isdisjoint(s["id"] for s in page2["items"])
        latest = client.get("/api/feed?topics=sport&sort=latest").json()["items"]
        assert [s["last_seen"] for s in latest] == sorted((s["last_seen"] for s in latest), reverse=True)
        assert client.get("/api/feed?topics=politik&sort=wild").status_code == 422
