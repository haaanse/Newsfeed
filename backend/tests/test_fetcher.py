import time

from app import db
from app.fetcher import cleanup, clean_text, normalize_url, parse_feed, run_fetch, truncate

from .conftest import FIXTURES


def test_clean_text_strips_html_and_entities():
    assert clean_text("<p>Hallo&nbsp;<b>Welt</b> &amp; mehr</p><script>x()</script>") == "Hallo Welt & mehr"
    assert clean_text(None) == ""


def test_truncate_on_word_boundary():
    assert truncate("eins zwei drei vier", 12) == "eins zwei …"
    assert truncate("kurz", 12) == "kurz"


def test_normalize_url_removes_tracking_and_fragment():
    url = "https://Example.org/a.html?utm_source=rss&id=7&wt_mc=x#top"
    assert normalize_url(url) == "https://example.org/a.html?id=7"


def test_parse_rss(cfg):
    items = parse_feed((FIXTURES / "rss_politik.xml").read_bytes(), cfg)
    by_title = {i.title: i for i in items}

    assert "Eintrag ohne Link" not in by_title
    haushalt = by_title["Bundestag beschließt Haushalt 2027"]
    assert haushalt.url == "https://example.org/politik/haushalt-2027-100.html?id=7"
    assert haushalt.image_url == "https://img.example.org/haushalt.jpg"
    assert "<" not in haushalt.summary and "&amp;" not in haushalt.summary
    assert len(haushalt.summary) <= 122
    assert haushalt.paywall is False

    assert by_title["Wahlrechtsreform: Was sich jetzt ändert"].image_url == "https://img.example.org/wahlrecht.jpg"
    assert by_title["Kommentar zur Koalition"].paywall is True              # ?reduced=true
    assert by_title["SPIEGEL+ Die geheimen Pläne der Regierung"].paywall is True
    assert by_title["Nur ein Bild per http"].image_url is None             # nur https-Bilder


def test_parse_atom(cfg):
    now = int(time.time())
    items = parse_feed((FIXTURES / "atom_tech.xml").read_bytes(), cfg, now)
    by_title = {i.title: i for i in items}
    assert by_title["Neuer Prozessor mit 128 Kernen vorgestellt"].image_url == "https://img.example.net/cpu.jpg"
    assert by_title["Neuer Prozessor mit 128 Kernen vorgestellt"].summary.endswith("…")
    assert by_title["heise+ | Test: Die besten Router"].paywall is True
    assert by_title["Artikel aus der Zukunft"].published_at == now


def test_run_fetch_stores_dedupes_and_tracks_errors(cfg, db_file, feeds):
    summary = run_fetch(cfg, db_file, feeds.client())
    assert summary["sources"] == 3                       # "pausiert" ist deaktiviert
    assert summary["ok"] == 2 and summary["errors"] == 1
    # 5 Politik + 4 Tech, davon 1 Duplikat (Haushalt)
    assert summary["new_articles"] == 8

    with db.connect(db_file) as conn:
        topics = [r[0] for r in conn.execute(
            """SELECT t.topic FROM articles a JOIN article_topics t ON t.article_id = a.id
               WHERE a.title LIKE 'Bundestag%' ORDER BY t.topic""")]
        assert topics == ["politik", "tech"]
        broken = conn.execute("SELECT error_count, last_error FROM sources WHERE id='kaputt'").fetchone()
        assert broken["error_count"] == 1 and "500" in broken["last_error"]
        assert conn.execute("SELECT etag FROM sources WHERE id='politik-feed'").fetchone()[0] == '"v1"'


def test_second_fetch_uses_etag(cfg, db_file, feeds):
    run_fetch(cfg, db_file, feeds.client())
    feeds.requests.clear()
    summary = run_fetch(cfg, db_file, feeds.client())
    politik = next(r for r in feeds.requests if r.url.path == "/politik.xml")
    assert politik.headers["if-none-match"] == '"v1"'
    assert summary["not_modified"] == 1
    assert summary["new_articles"] == 0
    with db.connect(db_file) as conn:
        assert conn.execute("SELECT error_count FROM sources WHERE id='kaputt'").fetchone()[0] == 2


def test_cleanup_removes_old_articles(cfg, db_file, feeds):
    run_fetch(cfg, db_file, feeds.client())
    deleted = cleanup(cfg, db_file, now=int(time.time()) + 30 * 86400)
    assert deleted == 8
    with db.connect(db_file) as conn:
        assert conn.execute("SELECT COUNT(*) FROM article_topics").fetchone()[0] == 0


def test_invalid_config_is_rejected():
    import pytest
    from app.config import ConfigError, validate
    with pytest.raises(ConfigError, match="unbekanntes Thema"):
        validate({"topics": [{"id": "tech"}],
                  "sources": [{"id": "x", "url": "https://x", "publisher": "X", "topic": "sport"}]})
