"""Anreicherung per Ollama: Embeddings, Story-Clustering, Themenzuordnung, Überblick.

Läuft nach jedem Abruf. Ist Ollama nicht erreichbar, wird der Schritt
übersprungen und beim nächsten Lauf nachgeholt – die App bleibt nutzbar.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np

from . import db
from .config import load_config
from .ollama import Ollama, OllamaUnavailable
from .regions import REGIONAL_TOPIC

log = logging.getLogger(__name__)

EMBED_HORIZON = 7 * 86400   # Embeddings für Artikel der letzten 7 Tage (Klassifikation)
MAX_EMBED_PER_RUN = 2000    # begrenzt die CPU-Last nach langer Pause


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def embedding_text(title: str, summary: str | None) -> str:
    # nomic-embed-text erwartet ein Aufgaben-Präfix
    return f"clustering: {title}. {summary or ''}".strip()


# ---------------------------------------------------------------------------
# 1) Embeddings
# ---------------------------------------------------------------------------
def embed_pending(conn, cfg: dict, ollama: Ollama, now: int) -> int:
    rows = conn.execute(
        """SELECT id, title, summary FROM articles
           WHERE embedding IS NULL AND published_at >= ? ORDER BY published_at DESC LIMIT ?""",
        (now - EMBED_HORIZON, MAX_EMBED_PER_RUN)).fetchall()
    size = cfg["ollama"]["batch_size"]
    for i in range(0, len(rows), size):
        batch = rows[i:i + size]
        vectors = ollama.embed([embedding_text(r["title"], r["summary"]) for r in batch])
        conn.executemany("UPDATE articles SET embedding = ? WHERE id = ?",
                         [(to_blob(v), r["id"]) for v, r in zip(vectors, batch)])
        conn.commit()  # Fortschritt sichern, falls Ollama mittendrin ausfällt
    return len(rows)


# ---------------------------------------------------------------------------
# 2) Clustering: gleiche Story aus verschiedenen Quellen gruppieren
# ---------------------------------------------------------------------------
CLUSTER_VERSION = "2"   # erhöhen, wenn sich das Verfahren ändert -> alles wird neu gruppiert


def reset_clusters_if_outdated(conn) -> bool:
    row = conn.execute("SELECT value FROM meta WHERE key = 'cluster_version'").fetchone()
    if row and row[0] == CLUSTER_VERSION:
        return False
    conn.execute("UPDATE articles SET cluster_id = NULL")
    conn.execute("DELETE FROM clusters")
    conn.execute("INSERT INTO meta (key, value) VALUES ('cluster_version', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (CLUSTER_VERSION,))
    log.info("Story-Gruppierung wird neu berechnet (Verfahren v%s)", CLUSTER_VERSION)
    return True


def cluster_pending(conn, cfg: dict, now: int) -> dict:
    """Ordnet neue Artikel bestehenden Storys zu oder legt neue an.

    Ein Artikel kommt nur in eine Story, wenn er ihren Artikeln IM DURCHSCHNITT ähnlich
    genug ist (Average Linkage). Der Vergleich mit einem normierten Mittelpunkt würde
    bei wachsenden Storys immer allgemeiner und ließe sie zu Riesen-Storys anwachsen.
    """
    window = int(cfg["ollama"]["cluster_window_hours"]) * 3600
    threshold = float(cfg["ollama"]["cluster_threshold"])
    rows = conn.execute(
        """SELECT id, embedding, published_at FROM articles
           WHERE cluster_id IS NULL AND embedding IS NOT NULL AND published_at >= ?
           ORDER BY published_at, id""", (now - window,)).fetchall()
    if not rows:
        return {"clustered": 0, "new_clusters": 0}

    dim = len(from_blob(rows[0]["embedding"]))
    oldest = rows[0]["published_at"]
    existing = [c for c in conn.execute(
        "SELECT id, centroid, size, first_seen, last_seen FROM clusters WHERE last_seen >= ?",
        (oldest - window,)) if len(from_blob(c["centroid"])) == dim]

    ids = [c["id"] for c in existing]
    sizes = [c["size"] for c in existing]
    first = [c["first_seen"] for c in existing]
    last = [c["last_seen"] for c in existing]
    # Mittelwert der (normierten) Artikelvektoren: means @ v = mittlere Ähnlichkeit zu allen Artikeln
    means = np.array([from_blob(c["centroid"]) for c in existing], dtype=np.float32).reshape(-1, dim)
    dirty: set[int] = set()
    new_clusters = 0

    for r in rows:
        v = from_blob(r["embedding"])
        ts = r["published_at"]
        best = -1
        if len(ids):
            sims = means @ v
            # nur Storys, die zeitlich passen (Fenster um den Artikel)
            in_window = np.array([ts - window <= f <= ts + window for f in first])
            sims = np.where(in_window, sims, -1.0)
            idx = int(np.argmax(sims))
            if sims[idx] >= threshold:
                best = idx
        if best >= 0:
            means[best] = (means[best] * sizes[best] + v) / (sizes[best] + 1)
            sizes[best] += 1
            first[best] = min(first[best], ts)
            last[best] = max(last[best], ts)
            dirty.add(best)
        else:
            cur = conn.execute(
                "INSERT INTO clusters (first_seen, last_seen, size, centroid) VALUES (?, ?, 1, ?)",
                (ts, ts, to_blob(v)))
            ids.append(cur.lastrowid)
            sizes.append(1)
            first.append(ts)
            last.append(ts)
            means = np.vstack([means, v[None, :]])
            new_clusters += 1
            best = len(ids) - 1
        conn.execute("UPDATE articles SET cluster_id = ? WHERE id = ?", (ids[best], r["id"]))

    for i in dirty:
        conn.execute("UPDATE clusters SET centroid = ?, size = ?, first_seen = ?, last_seen = ? WHERE id = ?",
                     (to_blob(means[i]), sizes[i], first[i], last[i], ids[i]))
    return {"clustered": len(rows), "new_clusters": new_clusters}


# ---------------------------------------------------------------------------
# 3) Themenzuordnung für Artikel aus allgemeinen Feeds (k-nächste Nachbarn)
# ---------------------------------------------------------------------------
def classify_pending(conn, cfg: dict, ollama: Ollama | None, now: int) -> dict:
    c = cfg["ollama"]["classify"]
    general = set(c["from_topics"])
    excluded = general | {REGIONAL_TOPIC}
    if not general:
        return {"classified": 0, "assigned": 0}
    marks = ",".join("?" * len(general))
    candidates = conn.execute(
        f"""SELECT a.id, a.title, a.summary, a.embedding FROM articles a
            WHERE a.classified = 0 AND a.embedding IS NOT NULL AND a.region IS NULL
              AND a.id IN (SELECT article_id FROM article_topics WHERE topic IN ({marks}))""",
        list(general)).fetchall()
    if not candidates:
        return {"classified": 0, "assigned": 0}

    labeled_rows = conn.execute(
        """SELECT a.id, a.embedding, GROUP_CONCAT(t.topic) AS topics FROM articles a
           JOIN article_topics t ON t.article_id = a.id
           WHERE a.embedding IS NOT NULL AND a.published_at >= ? AND a.region IS NULL
           GROUP BY a.id""", (now - EMBED_HORIZON,)).fetchall()
    labeled = [(r["id"], from_blob(r["embedding"]), set(r["topics"].split(",")) - excluded)
               for r in labeled_rows]
    labeled = [x for x in labeled if x[2]]
    assigned = 0
    uncertain = []
    if labeled:
        lab_ids = np.array([x[0] for x in labeled])
        matrix = np.vstack([x[1] for x in labeled])
        for cand in candidates:
            sims = matrix @ from_blob(cand["embedding"])
            sims[lab_ids == cand["id"]] = -1.0          # nicht mit sich selbst vergleichen
            order = np.argsort(-sims)[: c["neighbors"]]
            close = [i for i in order if sims[i] >= c["min_similarity"]]
            if len(close) < 3:
                uncertain.append(cand)
                continue
            votes: dict[str, int] = {}
            for i in close:
                for t in labeled[i][2]:
                    votes[t] = votes.get(t, 0) + 1
            topics = [t for t, n in votes.items() if n / len(close) >= c["min_share"]]
            for t in topics:
                conn.execute("INSERT OR IGNORE INTO article_topics (article_id, topic) VALUES (?, ?)",
                             (cand["id"], t))
            assigned += bool(topics)
    else:
        uncertain = list(candidates)

    if c["llm_fallback"] and ollama and uncertain:
        assigned += classify_with_llm(conn, cfg, ollama, uncertain[: c["llm_max_per_run"]])

    conn.executemany("UPDATE articles SET classified = 1 WHERE id = ?", [(r["id"],) for r in candidates])
    return {"classified": len(candidates), "assigned": assigned}


def classify_with_llm(conn, cfg: dict, ollama: Ollama, rows) -> int:
    excluded = set(cfg["ollama"]["classify"]["from_topics"]) | {REGIONAL_TOPIC}
    topics = {t["id"]: t["name"] for t in cfg["topics"] if t["id"] not in excluded}
    system = ("Du ordnest deutsche Nachrichtenmeldungen Themen zu. Antworte nur als JSON "
              '{"themen": [...]} mit 0 bis 2 Themen-IDs aus dieser Liste: '
              + ", ".join(f"{k} ({v})" for k, v in topics.items()))
    assigned = 0
    for r in rows:
        try:
            answer = ollama.chat_json(system, f"Titel: {r['title']}\nAnriss: {r['summary'] or ''}", 60)
        except OllamaUnavailable as e:
            log.warning("LLM-Themenzuordnung abgebrochen: %s", e)
            break
        chosen = [t for t in answer.get("themen", []) if isinstance(t, str) and t in topics][:2]
        for t in chosen:
            conn.execute("INSERT OR IGNORE INTO article_topics (article_id, topic) VALUES (?, ?)", (r["id"], t))
        assigned += bool(chosen)
    return assigned


# ---------------------------------------------------------------------------
# 4) Neutraler Ein-Satz-Überblick pro Story (optional)
# ---------------------------------------------------------------------------
SUMMARY_SYSTEM = (
    "Du bist eine neutrale Nachrichtenredaktion. Fasse die gemeinsame Kernaussage der folgenden "
    "Meldungen verschiedener Medien in genau EINEM sachlichen deutschen Satz mit höchstens 30 Wörtern "
    "zusammen. Keine Wertungen, keine Spekulationen, keine Informationen, die nicht in den Meldungen "
    'stehen. Antworte nur als JSON: {"satz": "..."}'
)


def summarize_clusters(conn, cfg: dict, ollama: Ollama, now: int) -> int:
    s = cfg["ollama"]["summaries"]
    window = int(cfg["ollama"]["cluster_window_hours"]) * 3600
    clusters = conn.execute(
        """SELECT c.id, c.size FROM clusters c
           WHERE c.last_seen >= ? AND (c.summary IS NULL OR c.size >= c.summary_size + 2)
             AND (SELECT COUNT(DISTINCT publisher) FROM articles WHERE cluster_id = c.id) >= ?
           ORDER BY c.size DESC LIMIT ?""", (now - window, s["min_sources"], s["max_per_run"])).fetchall()
    done = 0
    for c in clusters:
        arts = conn.execute(
            """SELECT publisher, title, summary FROM articles WHERE cluster_id = ?
               ORDER BY published_at LIMIT 8""", (c["id"],)).fetchall()
        text = "\n".join(f"- {a['publisher']}: {a['title']} – {a['summary'] or ''}" for a in arts)
        try:
            answer = ollama.chat_json(SUMMARY_SYSTEM, text, 120)
        except OllamaUnavailable as e:
            log.warning("Überblick abgebrochen: %s", e)
            break
        sentence = str(answer.get("satz", "")).strip()
        if 20 <= len(sentence) <= 320:
            conn.execute("UPDATE clusters SET summary = ?, summary_size = ? WHERE id = ?",
                         (sentence, c["size"], c["id"]))
            conn.commit()
            done += 1
    return done


# ---------------------------------------------------------------------------
def run(cfg: dict | None = None, db_file: Path | None = None, ollama: Ollama | None = None) -> dict:
    cfg = cfg or load_config()
    ollama = ollama or Ollama(cfg)
    now = int(time.time())
    started = time.time()
    stats: dict = {}
    try:
        ollama.check()
    except OllamaUnavailable as e:
        log.warning("Anreicherung übersprungen: %s", e)
        return {"skipped": str(e)}

    llm_needed = cfg["ollama"]["summaries"]["enabled"] or cfg["ollama"]["classify"]["llm_fallback"]
    llm_ok = False
    if llm_needed:
        try:
            ollama.check(need_llm=True)
            llm_ok = True
        except OllamaUnavailable as e:
            log.warning("LLM-Funktionen übersprungen: %s", e)

    with db.connect(db_file) as conn:
        try:
            stats["embedded"] = embed_pending(conn, cfg, ollama, now)
        except OllamaUnavailable as e:
            log.warning("Embeddings unvollständig: %s", e)
            stats["embed_error"] = str(e)
        reset_clusters_if_outdated(conn)
        stats.update(cluster_pending(conn, cfg, now))
        stats.update(classify_pending(conn, cfg, ollama if llm_ok else None, now))
        if llm_ok and cfg["ollama"]["summaries"]["enabled"]:
            stats["summaries"] = summarize_clusters(conn, cfg, ollama, now)
    stats["seconds"] = round(time.time() - started, 1)
    log.info("Anreicherung fertig: %s", stats)
    return stats
