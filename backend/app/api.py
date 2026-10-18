"""REST-API für die PWA. Keine Cookies, keine Nutzerkennungen, keine Logs mit IPs."""
from __future__ import annotations

import logging
import threading
import time

from fastapi import APIRouter, HTTPException, Query

from . import db, fetcher, regions, stories
from .config import load_config

router = APIRouter()
log = logging.getLogger(__name__)

_region_lock = threading.Lock()
_region_loading: set[str] = set()


@router.get("/health")
def health():
    with db.connect() as conn:
        last = conn.execute("SELECT MAX(last_fetch) FROM sources").fetchone()[0]
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        clustered = conn.execute("SELECT COUNT(*) FROM articles WHERE cluster_id IS NOT NULL").fetchone()[0]
    return {"status": "ok", "last_fetch": last, "articles": count, "clustered": clustered}


@router.get("/topics")
def topics():
    cfg = load_config()
    since = int(time.time()) - 48 * 3600
    with db.connect() as conn:
        counts = dict(conn.execute(
            """SELECT t.topic, COUNT(*) FROM article_topics t JOIN articles a ON a.id = t.article_id
               WHERE a.published_at >= ? AND a.region IS NULL AND (a.paywall = 0 OR ?) GROUP BY t.topic""",
            (since, int(not cfg["paywall"]["hide"])),
        ).fetchall())
    return [{"id": t["id"], "name": t["name"], "count_48h": counts.get(t["id"], 0)}
            for t in cfg["topics"]]


def _load_region_async(land: str) -> None:
    """Erstabruf eines Bundeslandes im Hintergrund (nur einmal gleichzeitig)."""
    with _region_lock:
        if land in _region_loading:
            return
        _region_loading.add(land)

    def work():
        try:
            fetcher.run_fetch(only=regions.sources_for(load_config(), land))
        except Exception:  # noqa: BLE001
            log.exception("Regionalabruf %s fehlgeschlagen", land)
        finally:
            with _region_lock:
                _region_loading.discard(land)

    threading.Thread(target=work, name=f"region-{land}", daemon=True).start()


@router.get("/feed")
def feed(
    topics: str = Query(..., description="Kommagetrennte Themen-IDs, z. B. tech,ki"),
    sort: str = Query("top", pattern="^(top|latest)$"),
    land: str | None = Query(None, description="Bundesland-Kürzel für 'regional', z. B. BY"),
    kreis: str | None = Query(None, description="Kreisschlüssel, z. B. 09187"),
    only_local: bool = Query(False),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0, le=5000),
):
    cfg = load_config()
    valid = {t["id"] for t in cfg["topics"]}
    wanted = [t for t in dict.fromkeys(topics.split(",")) if t]
    if not wanted or any(t not in valid for t in wanted):
        raise HTTPException(400, "Unbekanntes Thema")
    if land is not None and not regions.is_land(land):
        raise HTTPException(400, "Unbekanntes Bundesland")
    if kreis is not None and (not land or not regions.kreis(land, kreis)):
        raise HTTPException(400, "Unbekannter Kreis")

    pending = False
    with db.connect() as conn:
        if regions.REGIONAL_TOPIC in wanted and land:
            regions.touch(conn, land)
            fetched = conn.execute("SELECT 1 FROM sources WHERE region = ? AND last_fetch IS NOT NULL LIMIT 1",
                                   (land,)).fetchone()
            if not fetched:
                conn.commit()
                _load_region_async(land)
                pending = True
        result = stories.build(conn, cfg, stories.Query(
            topics=wanted, sort=sort, land=land, kreis=kreis, only_local=only_local,
            limit=limit, offset=offset))
    result["pending"] = pending
    return result


@router.get("/regions")
def region_list():
    """Bundesländer und ihre Kreise (für die Auswahl in den Einstellungen)."""
    return {
        "attribution": regions.data()["_quelle"],
        "laender": [{"id": code, "name": land["name"],
                     "kreise": [{"id": kid, "name": k["name"]} for kid, k in land["kreise"].items()]}
                    for code, land in regions.laender().items()],
    }


@router.get("/sources")
def sources():
    """Status aller Quellen – hilfreich, um kaputte Feed-URLs zu finden."""
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT s.*, (SELECT COUNT(*) FROM articles a WHERE a.source_id = s.id) AS articles
               FROM sources s ORDER BY s.topic, s.id""").fetchall()
    return [{k: r[k] for k in ("id", "name", "publisher", "topic", "region", "url", "weight", "last_fetch",
                               "last_ok", "error_count", "last_error", "last_new", "articles")}
            for r in rows]
