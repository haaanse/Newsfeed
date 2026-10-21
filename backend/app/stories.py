"""Baut aus Artikeln Storys (ein Cluster = eine Story) und rankt sie."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import regions
from .ranking import FormulaError

ARTICLE_COLS = ("a.id, a.url, a.title, a.summary, a.image_url, a.publisher, a.source_id, "
                "a.published_at, a.cluster_id, a.region")


@dataclass
class Query:
    topics: list[str]
    sort: str = "top"                 # top | latest
    land: str | None = None           # Bundesland für "regional"
    kreis: str | None = None          # Kreisschlüssel für Lokalbezug
    only_local: bool = False
    limit: int = 30
    offset: int = 0
    now: int = field(default_factory=lambda: int(time.time()))


def _candidates(conn, cfg: dict, q: Query) -> list:
    general = [t for t in q.topics if t != regions.REGIONAL_TOPIC]
    parts, params = [], []
    if general:
        parts.append(f"""a.region IS NULL AND a.id IN (SELECT article_id FROM article_topics
                         WHERE topic IN ({','.join('?' * len(general))}))""")
        params += general
    if regions.REGIONAL_TOPIC in q.topics and q.land:
        parts.append("a.region = ?")
        params.append(q.land)
    if not parts:
        return []
    where = [f"({' OR '.join(parts)})"]
    if cfg["paywall"]["hide"]:
        where.append("a.paywall = 0")
    if q.sort == "top":
        where.append("a.published_at >= ?")
        params.append(q.now - int(cfg["ranking"]["window_hours"]) * 3600)
    return conn.execute(f"SELECT {ARTICLE_COLS} FROM articles a WHERE {' AND '.join(where)}", params).fetchall()


def _cluster_mates(conn, cfg: dict, cluster_ids: set[int]) -> list:
    if not cluster_ids:
        return []
    ids = list(cluster_ids)
    rows = []
    paywall = "AND a.paywall = 0" if cfg["paywall"]["hide"] else ""
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        rows += conn.execute(
            f"SELECT {ARTICLE_COLS} FROM articles a WHERE a.cluster_id IN ({','.join('?' * len(chunk))}) {paywall}",
            chunk).fetchall()
    return rows


def build(conn, cfg: dict, q: Query) -> dict:
    candidates = _candidates(conn, cfg, q)
    cluster_ids = {r["cluster_id"] for r in candidates if r["cluster_id"]}
    groups: dict[str, dict] = {}
    for r in list(candidates) + _cluster_mates(conn, cfg, cluster_ids):
        key = f"c{r['cluster_id']}" if r["cluster_id"] else f"a{r['id']}"
        groups.setdefault(key, {})[r["id"]] = r

    weights = {s["id"]: s["weight"] for s in cfg["sources"]}
    topic_rows = _topics_for(conn, [aid for g in groups.values() for aid in g])
    summaries = _summaries(conn, cluster_ids)
    matcher = regions.kreis_matcher(q.land, q.kreis) if q.land and q.kreis else None
    formula = cfg["ranking"]["_formula"]

    stories = []
    for key, members in groups.items():
        arts = sorted(members.values(), key=lambda r: r["published_at"])
        # Pro Verlag nur der erste Artikel; Verlag zählt einmal
        by_publisher: dict[str, object] = {}
        for a in arts:
            by_publisher.setdefault(a["publisher"], a)
        pub_weight = {p: weights.get(a["source_id"], 1.2 if a["region"] else 1.0) for p, a in by_publisher.items()}
        lead = max(by_publisher.values(), key=lambda a: (pub_weight[a["publisher"]], -a["published_at"]))
        first_seen, last_seen = arts[0]["published_at"], arts[-1]["published_at"]
        local = bool(matcher and any(matcher.search(f"{a['title']} {a['summary'] or ''}") for a in arts))
        # "Nur Lokalmeldungen" betrifft nur Regionalmeldungen – in "Mein Feed" bleiben die übrigen Themen
        regional_only = all(a["region"] for a in arts)
        if q.only_local and matcher and regional_only and not local:
            continue
        values = dict(
            sources=len(by_publisher),
            articles=len(arts),
            age_hours=max(0.0, (q.now - first_seen) / 3600),
            update_hours=max(0.0, (q.now - last_seen) / 3600),
            weight=sum(pub_weight.values()) / len(pub_weight),
            max_weight=max(pub_weight.values()),
            local=int(local),
        )
        try:
            score = formula.score(**values)
        except FormulaError:
            score = 0.0
        topics = sorted({t for a in arts for t in topic_rows.get(a["id"], ())})
        image = lead["image_url"] or next((a["image_url"] for a in arts if a["image_url"]), None)
        stories.append({
            "id": key,
            "title": lead["title"],
            "summary": lead["summary"] or "",
            "url": lead["url"],
            "publisher": lead["publisher"],
            "published_at": lead["published_at"],
            "image_url": image,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "source_count": len(by_publisher),
            "sources": [{"publisher": a["publisher"], "title": a["title"], "url": a["url"],
                         "published_at": a["published_at"]}
                        for p, a in by_publisher.items() if a is not lead],
            "topics": topics,
            "overview": summaries.get(lead["cluster_id"]) if lead["cluster_id"] else None,
            "local": local,
            "score": round(score, 3),
        })

    if q.sort == "top":
        stories.sort(key=lambda s: (s["score"], s["last_seen"]), reverse=True)
    else:
        stories.sort(key=lambda s: (s["last_seen"], s["id"]), reverse=True)
    page = stories[q.offset:q.offset + q.limit]
    more = q.offset + q.limit < len(stories)
    return {"items": page, "total": len(stories), "next_offset": q.offset + q.limit if more else None}


def _topics_for(conn, article_ids: list[int]) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    for i in range(0, len(article_ids), 500):
        chunk = article_ids[i:i + 500]
        for r in conn.execute(
                f"SELECT article_id, topic FROM article_topics WHERE article_id IN ({','.join('?' * len(chunk))})",
                chunk):
            result.setdefault(r[0], []).append(r[1])
    return result


def _summaries(conn, cluster_ids: set[int]) -> dict[int, str]:
    if not cluster_ids:
        return {}
    ids = list(cluster_ids)
    result = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        result.update(conn.execute(
            f"SELECT id, summary FROM clusters WHERE summary IS NOT NULL AND id IN ({','.join('?' * len(chunk))})",
            chunk).fetchall())
    return result
