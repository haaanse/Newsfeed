"""Übersicht, warum wie viele Meldungen im Feed landen.

Aufruf:  docker compose exec newsfeed python -m app.diagnose
"""
import time

import numpy as np

from . import db, stories
from .config import load_config
from .enrich import from_blob


def main() -> None:
    cfg = load_config()
    now = int(time.time())
    since = now - 48 * 3600
    with db.connect() as conn:
        q = lambda sql, *p: conn.execute(sql, p).fetchone()[0]  # noqa: E731
        total = q("SELECT COUNT(*) FROM articles")
        recent = q("SELECT COUNT(*) FROM articles WHERE published_at >= ?", since)
        paywall = q("SELECT COUNT(*) FROM articles WHERE paywall = 1")
        embedded = q("SELECT COUNT(*) FROM articles WHERE embedding IS NOT NULL")
        clustered = q("SELECT COUNT(*) FROM articles WHERE cluster_id IS NOT NULL")
        print(f"Artikel gesamt: {total}  |  letzte 48 h: {recent}")
        print(f"Paywall (ausgeblendet): {paywall}  ({100 * paywall // max(total, 1)} %)")
        print(f"Mit Embedding: {embedded}  |  gruppiert: {clustered}")
        print(f"Schwelle cluster_threshold: {cfg['ollama']['cluster_threshold']}\n")

        print("Größte Storys (Artikel pro Story):")
        for r in conn.execute("""SELECT cluster_id, COUNT(*) n, COUNT(DISTINCT publisher) p,
                                        MIN(title) t FROM articles WHERE cluster_id IS NOT NULL
                                 GROUP BY cluster_id ORDER BY n DESC LIMIT 8"""):
            print(f"  {r['n']:4} Artikel / {r['p']:2} Verlage  z. B. „{r['t'][:70]}“")

        print("\nPaywall-Treffer pro Quelle:")
        for r in conn.execute("""SELECT source_id, SUM(paywall) pw, COUNT(*) n FROM articles
                                 GROUP BY source_id HAVING pw > 0 ORDER BY pw DESC LIMIT 10"""):
            print(f"  {r['source_id']:<24} {r['pw']:4} von {r['n']}")

        print("\nStorys pro Thema (Top = 48 h | Neueste = alle):")
        for t in cfg["topics"]:
            if t["id"] == "regional":
                continue
            top = stories.build(conn, cfg, stories.Query(topics=[t["id"]], sort="top", limit=1))["total"]
            latest = stories.build(conn, cfg, stories.Query(topics=[t["id"]], sort="latest", limit=1))["total"]
            print(f"  {t['name']:<14} {top:5} | {latest:5}")

        similarity_report(conn, since)


def similarity_report(conn, since: int) -> None:
    """Ähnlichkeit jedes Artikels zum ähnlichsten Artikel eines ANDEREN Verlags.

    Gleiche Story bei zwei Verlagen -> hoher Wert. Die Beispielpaare zeigen,
    ab welchem Wert es wirklich dieselbe Nachricht ist (-> cluster_threshold).
    """
    rows = conn.execute("""SELECT id, publisher, title, embedding FROM articles
                           WHERE embedding IS NOT NULL AND published_at >= ? AND region IS NULL""",
                        (since,)).fetchall()
    if len(rows) < 10:
        print("\nZu wenige Artikel mit Embedding für die Ähnlichkeitsanalyse.")
        return
    m = np.vstack([from_blob(r["embedding"]) for r in rows])
    pubs = np.array([r["publisher"] for r in rows])
    sims = m @ m.T
    sims[pubs[:, None] == pubs[None, :]] = -1.0          # nur andere Verlage
    best = sims.argmax(axis=1)
    best_sim = sims[np.arange(len(rows)), best]

    print("\nÄhnlichkeit zum ähnlichsten Artikel eines anderen Verlags (letzte 48 h):")
    edges = [0.0, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.01]
    for lo, hi in zip(edges, edges[1:]):
        n = int(((best_sim >= lo) & (best_sim < hi)).sum())
        print(f"  {lo:.2f}–{min(hi, 1):.2f}: {n:5}  {'#' * min(60, n // 5)}")
    print(f"  Median: {np.median(best_sim):.3f}")

    print("\nBeispielpaare je Bereich (Titel A  ||  Titel B):")
    rng = np.random.default_rng(1)
    for lo in (0.70, 0.75, 0.80, 0.85, 0.90):
        idx = np.where((best_sim >= lo) & (best_sim < lo + 0.05))[0]
        print(f"  --- {lo:.2f}–{lo + 0.05:.2f} ---")
        for i in rng.choice(idx, size=min(4, len(idx)), replace=False) if len(idx) else []:
            j = best[i]
            print(f"   {best_sim[i]:.3f}  {rows[i]['title'][:60]}  ||  {rows[j]['title'][:60]}")


if __name__ == "__main__":
    main()
