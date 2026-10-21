from fastapi.testclient import TestClient

from app import api, db, regions
from app.fetcher import all_sources
from app.main import app

from .helpers import add


def test_region_data_complete():
    laender = regions.laender()
    assert len(laender) == 16
    assert sum(len(l["kreise"]) for l in laender.values()) > 390
    assert regions.kreis("BY", "09187")["name"] == "Landkreis Rosenheim"


def test_kreis_matcher():
    m = regions.kreis_matcher("BY", "09187")
    assert m.search("Unfall bei Bad Aibling: Zwei Verletzte")
    assert m.search("Neues Hallenbad in Rosenheim eröffnet")
    assert not m.search("Stau auf der A9 bei Ingolstadt")
    assert not m.search("Rosenheimer Straße in München gesperrt")  # kein Teilwort-Treffer


def test_regional_sources_only_for_requested_lands(cfg, db_file):
    with db.connect(db_file) as conn:
        assert not [s for s in all_sources(conn, cfg) if s.get("region")]
        regions.touch(conn, "BY")
        regional = [s for s in all_sources(conn, cfg) if s.get("region")]
    assert [s["id"] for s in regional] == ["regional-by"]
    assert regional[0]["url"].endswith("/regional/bayern/index~rss2.xml")


def test_regional_feed_triggers_fetch_and_filters_kreis(cfg, db_file, monkeypatch):
    started = []
    monkeypatch.setattr(api, "_load_region_async", started.append)
    with TestClient(app) as client:
        first = client.get("/api/feed?topics=regional&land=BY").json()
        assert first["pending"] is True and started == ["BY"]

        with db.connect(db_file) as conn:
            add(conn, cfg, "regional-by", "tagesschau Bayern", "regional",
                "Unfall bei Bad Aibling: Zwei Verletzte", region="BY")
            add(conn, cfg, "regional-by", "tagesschau Bayern", "regional",
                "Landtag in München debattiert Haushalt", region="BY", hours_ago=0.5)
            add(conn, cfg, "regional-sn", "tagesschau Sachsen", "regional",
                "Dresden feiert Stadtfest", region="SN")
            conn.execute("UPDATE sources SET last_fetch = 1 WHERE region = 'BY'")
            conn.execute("INSERT OR IGNORE INTO sources (id, name, publisher, url, region, last_fetch) "
                         "VALUES ('regional-by', 'x', 'x', 'x', 'BY', 1)")

        feed = client.get("/api/feed?topics=regional&land=BY&kreis=09187").json()
        assert feed["pending"] is False
        titles = [s["title"] for s in feed["items"]]
        assert titles[0] == "Unfall bei Bad Aibling: Zwei Verletzte"     # Lokalbezug hebt das Ranking
        assert "Dresden feiert Stadtfest" not in titles
        assert [s["local"] for s in feed["items"]] == [True, False]

        local = client.get("/api/feed?topics=regional&land=BY&kreis=09187&only_local=true").json()
        assert [s["title"] for s in local["items"]] == ["Unfall bei Bad Aibling: Zwei Verletzte"]

        # Regionalmeldungen tauchen nicht in den normalen Themen auf
        assert client.get("/api/feed?topics=top,politik").json()["total"] == 0

        assert client.get("/api/feed?topics=regional&land=XX").status_code == 400
        assert client.get("/api/feed?topics=regional&land=BY&kreis=99999").status_code == 400
        regions_json = client.get("/api/regions").json()
        assert len(regions_json["laender"]) == 16 and "Destatis" in regions_json["attribution"]


def test_region_request_stores_only_land(cfg, db_file):
    with db.connect(db_file) as conn:
        regions.touch(conn, "HE")
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(region_requests)")]
    assert cols == ["region", "last_requested"]


def test_only_local_keeps_other_topics_in_mixed_feed(cfg, db_file, monkeypatch):
    """Regression: "Nur Lokalmeldungen" hat "Mein Feed" komplett geleert."""
    monkeypatch.setattr(api, "_load_region_async", lambda land: None)
    with db.connect(db_file) as conn:
        add(conn, cfg, "politik-feed", "Beispiel", "politik", "Bundestag beschließt Haushalt")
        add(conn, cfg, "regional-by", "tagesschau Bayern", "regional",
            "Unfall bei Bad Aibling: Zwei Verletzte", region="BY")
        add(conn, cfg, "regional-by", "tagesschau Bayern", "regional",
            "Nürnberg plant neue U-Bahn-Linie", region="BY")
        conn.execute("INSERT OR IGNORE INTO sources (id, name, publisher, url, region, last_fetch) "
                     "VALUES ('regional-by', 'x', 'x', 'x', 'BY', 1)")
    with TestClient(app) as client:
        items = client.get("/api/feed?topics=politik,regional&land=BY&kreis=09187&only_local=true").json()["items"]
    titles = {s["title"] for s in items}
    assert titles == {"Bundestag beschließt Haushalt", "Unfall bei Bad Aibling: Zwei Verletzte"}
