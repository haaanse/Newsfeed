"""Zeigt die aktuell größten Storys – hilft beim Einstellen von cluster_threshold.

Aufruf:  docker compose exec newsfeed python -m app.inspect_clusters [anzahl]
"""
import sys
import time

from . import db
from .config import load_config


def main(limit: int = 15) -> None:
    cfg = load_config()
    since = int(time.time()) - int(cfg["ollama"]["cluster_window_hours"]) * 3600
    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM articles WHERE published_at >= ?", (since,)).fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM articles WHERE published_at >= ? AND cluster_id IS NOT NULL",
                            (since,)).fetchone()[0]
        print(f"Schwelle {cfg['ollama']['cluster_threshold']} – {done}/{total} Artikel der letzten "
              f"{cfg['ollama']['cluster_window_hours']} h gruppiert\n")
        clusters = conn.execute(
            """SELECT cluster_id, COUNT(DISTINCT publisher) AS pubs, COUNT(*) AS n FROM articles
               WHERE cluster_id IS NOT NULL AND published_at >= ?
               GROUP BY cluster_id ORDER BY pubs DESC, n DESC LIMIT ?""", (since, limit)).fetchall()
        for c in clusters:
            print(f"■ Story {c['cluster_id']}: {c['pubs']} Verlage, {c['n']} Artikel")
            for a in conn.execute("SELECT publisher, title FROM articles WHERE cluster_id = ? ORDER BY published_at",
                                  (c["cluster_id"],)):
                print(f"   {a['publisher']:<18.18} {a['title'][:90]}")
            print()
    print("Zu viele fremde Meldungen in einer Story -> cluster_threshold erhöhen (z. B. 0.84).\n"
          "Gleiche Meldungen nicht zusammengefasst -> cluster_threshold senken (z. B. 0.76).\n"
          "Neu gruppieren: docker compose exec newsfeed python -m app.inspect_clusters --reset")


def reset() -> None:
    with db.connect() as conn:
        conn.execute("UPDATE articles SET cluster_id = NULL")
        conn.execute("DELETE FROM clusters")
    print("Gruppierung zurückgesetzt – sie wird beim nächsten Abruf neu berechnet.")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset()
    else:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 15)
