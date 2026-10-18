"""Regionaldaten (Bundesländer, Kreise, Ortsnamen) und regionale Quellen."""
from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "regionen.json"
REGIONAL_TOPIC = "regional"


@lru_cache(maxsize=1)
def data() -> dict:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def laender() -> dict:
    return data()["laender"]


def is_land(code: str | None) -> bool:
    return bool(code) and code in laender()


def kreis(land: str, kreis_id: str) -> dict | None:
    return laender().get(land, {}).get("kreise", {}).get(kreis_id)


@lru_cache(maxsize=64)
def kreis_matcher(land: str, kreis_id: str) -> re.Pattern | None:
    """Regex über alle Ortsnamen des Kreises (Groß-/Kleinschreibung wird beachtet)."""
    k = kreis(land, kreis_id)
    if not k or not k["orte"]:
        return None
    names = sorted(k["orte"], key=len, reverse=True)
    return re.compile(r"(?<![\wÄÖÜäöüß-])(?:" + "|".join(map(re.escape, names)) + r")(?![\wÄÖÜäöüß])")


def sources_for(cfg: dict, land: str) -> list[dict]:
    """Quellen eines Bundeslandes: tagesschau-Regionalfeed plus eigene Zusatzquellen."""
    info = laender()[land]
    result = [{
        "id": f"regional-{land.lower()}",
        "name": f"tagesschau {info['name']}",
        "publisher": f"tagesschau {info['name']}",
        "url": info["feed"],
        "topic": REGIONAL_TOPIC,
        "weight": 1.2,
        "enabled": True,
        "region": land,
    }]
    for s in cfg["regional"]["extra_sources"].get(land) or []:
        result.append({"name": s["publisher"], "weight": 1.0, "enabled": True, **s,
                       "id": f"regional-{land.lower()}-{s['id']}", "topic": REGIONAL_TOPIC, "region": land})
    return result


def touch(conn, land: str) -> bool:
    """Merkt, dass ein Land angefragt wurde. Gibt True zurück, wenn es neu ist."""
    now = int(time.time())
    row = conn.execute("SELECT last_requested FROM region_requests WHERE region = ?", (land,)).fetchone()
    # Höchstens einmal pro Stunde schreiben – reicht für keep_days völlig aus
    if row is None or now - row[0] > 3600:
        conn.execute("""INSERT INTO region_requests (region, last_requested) VALUES (?, ?)
                        ON CONFLICT(region) DO UPDATE SET last_requested = excluded.last_requested""",
                     (land, now))
    return row is None


def active(conn, cfg: dict) -> list[str]:
    cutoff = int(time.time()) - int(cfg["regional"]["keep_days"]) * 86400
    return [r[0] for r in conn.execute(
        "SELECT region FROM region_requests WHERE last_requested >= ? ORDER BY region", (cutoff,))
        if is_land(r[0])]
