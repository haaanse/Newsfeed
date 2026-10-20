"""Übersicht, warum wie viele Meldungen im Feed landen.

Aufruf:  docker compose exec newsfeed python -m app.diagnose
"""
import time

from . import db, stories
from .config import load_config


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


if __name__ == "__main__":
    main()
