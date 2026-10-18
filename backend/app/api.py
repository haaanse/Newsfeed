"""REST-API für die PWA. Keine Cookies, keine Nutzerkennungen, keine Logs mit IPs."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query

from . import db
from .config import load_config

router = APIRouter()


@router.get("/health")
def health():
    with db.connect() as conn:
        last = conn.execute("SELECT MAX(last_fetch) FROM sources").fetchone()[0]
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    return {"status": "ok", "last_fetch": last, "articles": count}


@router.get("/topics")
def topics():
    cfg = load_config()
    since = int(time.time()) - 48 * 3600
    with db.connect() as conn:
        counts = dict(conn.execute(
            """SELECT t.topic, COUNT(*) FROM article_topics t JOIN articles a ON a.id = t.article_id
               WHERE a.published_at >= ? AND (a.paywall = 0 OR ?) GROUP BY t.topic""",
            (since, int(not cfg["paywall"]["hide"])),
        ).fetchall())
    return [{"id": t["id"], "name": t["name"], "count_48h": counts.get(t["id"], 0)}
            for t in cfg["topics"]]


@router.get("/articles")
def articles(
    topics: str = Query(..., description="Kommagetrennte Themen-IDs, z. B. tech,ki"),
    limit: int = Query(40, ge=1, le=100),
    before: str | None = Query(None, description="Cursor aus 'next' der vorherigen Antwort"),
):
    cfg = load_config()
    valid = {t["id"] for t in cfg["topics"]}
    wanted = [t for t in dict.fromkeys(topics.split(",")) if t]
    if not wanted or any(t not in valid for t in wanted):
        raise HTTPException(400, "Unbekanntes Thema")

    params: list = list(wanted)
    where = [f"a.id IN (SELECT article_id FROM article_topics WHERE topic IN ({','.join('?' * len(wanted))}))"]
    if cfg["paywall"]["hide"]:
        where.append("a.paywall = 0")
    if before:
        try:
            ts, aid = (int(x) for x in before.split("_", 1))
        except ValueError:
            raise HTTPException(400, "Ungültiger Cursor") from None
        where.append("(a.published_at, a.id) < (?, ?)")
        params += [ts, aid]

    with db.connect() as conn:
        rows = conn.execute(
            f"""SELECT a.id, a.url, a.title, a.summary, a.image_url, a.publisher, a.source_id,
                       a.published_at, a.paywall,
                       (SELECT GROUP_CONCAT(topic) FROM article_topics WHERE article_id = a.id) AS topics
                FROM articles a
                WHERE {' AND '.join(where)}
                ORDER BY a.published_at DESC, a.id DESC
                LIMIT ?""",
            params + [limit],
        ).fetchall()

    items = [{
        "id": r["id"],
        "url": r["url"],
        "title": r["title"],
        "summary": r["summary"] or "",
        "image_url": r["image_url"],
        "publisher": r["publisher"],
        "published_at": r["published_at"],
        "paywall": bool(r["paywall"]),
        "topics": (r["topics"] or "").split(","),
    } for r in rows]
    nxt = f"{items[-1]['published_at']}_{items[-1]['id']}" if len(items) == limit else None
    return {"items": items, "next": nxt}


@router.get("/sources")
def sources():
    """Status aller Quellen – hilfreich, um kaputte Feed-URLs zu finden."""
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT s.*, (SELECT COUNT(*) FROM articles a WHERE a.source_id = s.id) AS articles
               FROM sources s ORDER BY s.topic, s.id""").fetchall()
    return [{k: r[k] for k in ("id", "name", "publisher", "topic", "url", "weight", "last_fetch",
                               "last_ok", "error_count", "last_error", "last_new", "articles")}
            for r in rows]
