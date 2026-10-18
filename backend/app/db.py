"""SQLite-Zugriff. Bewusst ohne ORM – das Schema ist klein und überschaubar."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import ROOT

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    publisher     TEXT NOT NULL,
    url           TEXT NOT NULL,
    topic         TEXT,
    weight        REAL NOT NULL DEFAULT 1.0,
    etag          TEXT,
    last_modified TEXT,
    last_fetch    INTEGER,
    last_ok       INTEGER,
    error_count   INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    last_new      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY,
    url          TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    summary      TEXT,
    image_url    TEXT,
    source_id    TEXT NOT NULL,
    publisher    TEXT NOT NULL,
    published_at INTEGER NOT NULL,
    fetched_at   INTEGER NOT NULL,
    paywall      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS article_topics (
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    topic      TEXT NOT NULL,
    PRIMARY KEY (article_id, topic)
);
CREATE INDEX IF NOT EXISTS idx_article_topics_topic ON article_topics(topic, article_id);

CREATE TABLE IF NOT EXISTS clusters (
    id          INTEGER PRIMARY KEY,
    first_seen  INTEGER NOT NULL,
    last_seen   INTEGER NOT NULL,
    size        INTEGER NOT NULL DEFAULT 1,
    centroid    BLOB NOT NULL,
    summary     TEXT,
    summary_size INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_clusters_last_seen ON clusters(last_seen);

-- Nur das Bundesland und der Zeitpunkt – keine Geräte- oder Nutzerdaten.
CREATE TABLE IF NOT EXISTS region_requests (
    region         TEXT PRIMARY KEY,
    last_requested INTEGER NOT NULL
);
"""

# Spalten, die nach dem MVP dazugekommen sind (bestehende Datenbanken werden ergänzt)
MIGRATIONS = {
    "articles": {
        "embedding": "BLOB",
        "cluster_id": "INTEGER REFERENCES clusters(id) ON DELETE SET NULL",
        "region": "TEXT",
        "classified": "INTEGER NOT NULL DEFAULT 0",
    },
    "sources": {
        "region": "TEXT",
    },
}
POST_MIGRATION = """
CREATE INDEX IF NOT EXISTS idx_articles_cluster ON articles(cluster_id);
CREATE INDEX IF NOT EXISTS idx_articles_pending ON articles(embedding) WHERE embedding IS NULL;
"""


def db_path() -> Path:
    return Path(os.environ.get("NEWSFEED_DB", ROOT / "data" / "newsfeed.db"))


@contextmanager
def connect(path: Path | None = None):
    conn = sqlite3.connect(path or db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: Path | None = None) -> None:
    path = Path(path or db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        for table, columns in MIGRATIONS.items():
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        conn.executescript(POST_MIGRATION)
