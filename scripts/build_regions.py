"""Erzeugt backend/app/data/regionen.json aus dem Gemeindeverzeichnis (GV100AD) von Destatis.

Quelle: npm-Paket "gemeindeverzeichnis" (MIT) mit Daten des Statistischen Bundesamts,
Datenlizenz Deutschland – Namensnennung – Version 2.0, Stand 31.03.2017.

Aufruf:  python scripts/build_regions.py <pfad/zu/package>
"""
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "backend" / "app" / "data" / "regionen.json"

# Länder-Kürzel und tagesschau-Regionalseiten (Inhalte der jeweiligen Landesrundfunkanstalt)
LAENDER = {
    "01": ("SH", "schleswigholstein"), "02": ("HH", "hamburg"), "03": ("NI", "niedersachsen"),
    "04": ("HB", "bremen"), "05": ("NW", "nordrheinwestfalen"), "06": ("HE", "hessen"),
    "07": ("RP", "rheinlandpfalz"), "08": ("BW", "badenwuerttemberg"), "09": ("BY", "bayern"),
    "10": ("SL", "saarland"), "11": ("BE", "berlin"), "12": ("BB", "brandenburg"),
    "13": ("MV", "mecklenburgvorpommern"), "14": ("SN", "sachsen"), "15": ("ST", "sachsenanhalt"),
    "16": ("TH", "thueringen"),
}

# Ortsnamen, die zugleich häufige Wörter sind -> nur bei großen Städten verwenden
STOPWORDS = {
    "Au", "Bach", "Bad", "Berg", "Brand", "Buch", "Burg", "Damm", "Dorf", "Elend", "Essen", "Feld",
    "Fehl", "Freiheit", "Frieden", "Grund", "Hagen", "Halle", "Hausen", "Heide", "Hof", "Holz",
    "Insel", "Kirchen", "Kranichfeld", "Lage", "Linden", "Mark", "Moos", "Rain", "Rehe", "Ried",
    "Stein", "Tal", "Wald", "Weil", "Weiler", "Werder", "Wiese", "Zell", "Senden", "Bergen",
    "Wesel", "Gera", "Laufen", "Ohne", "Ende", "Kappeln", "Lauf", "Bühl", "Rotenburg", "Stadt",
}
SUFFIX_SPLIT = re.compile(r"\s+(?:a\.|i\.|b\.|v\.d\.|am |an der |im |in der |ob der |bei |\()")


def clean(name: str) -> str:
    return name.split(",")[0].strip()


def variants(name: str, population: int) -> set[str]:
    base = clean(name)
    out = {base}
    short = SUFFIX_SPLIT.split(base)[0].strip()
    if short != base:
        out.add(short)
    return {v for v in out if len(v) >= 4 and (v not in STOPWORDS or population >= 100_000)}


def kreis_label(k: dict) -> str:
    name, typ = k["name"], k["typ"]["name"]
    base = clean(name)
    if typ in ("kreisfreie-stadt", "stadtkreis"):
        return f"{base} (Stadt)"
    if typ == "landkreis":
        return base if base.lower().startswith(("landkreis", "region")) else f"Landkreis {base}"
    if typ == "kreis":
        return base if "kreis" in base.lower() else f"Kreis {base}"
    return base


def main(pkg: Path):
    read = lambda f: [json.loads(line) for line in open(pkg / f, encoding="utf-8")]
    laender = read("laender.ndjson")
    kreise = read("kreise.ndjson")
    gemeinden = read("gemeinden.ndjson")

    result = {}
    for land in laender:
        code, slug = LAENDER[land["schlüssel"]["land"]]
        result[code] = {
            "name": land["name"],
            "feed": f"https://www.tagesschau.de/inland/regional/{slug}/index~rss2.xml",
            "kreise": {},
        }
    land_by_nr = {l["schlüssel"]["land"]: LAENDER[l["schlüssel"]["land"]][0] for l in laender}
    for k in kreise:
        nr = k["schlüssel"]["nummer"]
        result[land_by_nr[nr[:2]]]["kreise"][nr] = {"name": kreis_label(k), "orte": set()}
        result[land_by_nr[nr[:2]]]["kreise"][nr]["orte"] |= variants(k["name"], 0) | (
            variants(k["sitz"], 0) if k.get("sitz") else set())
    for g in gemeinden:
        if g["typ"]["name"].startswith("gemeindefreies"):
            continue
        s = g["schlüssel"]
        nr = s["land"] + s["regierungsbezirk"] + s["kreis"]
        result[land_by_nr[s["land"]]]["kreise"][nr]["orte"] |= variants(g["name"], g.get("bevölkerung") or 0)

    for land in result.values():
        for k in land["kreise"].values():
            k["orte"] = sorted(k["orte"])
        land["kreise"] = dict(sorted(land["kreise"].items(),
                                    key=lambda kv: re.sub(r"^(Landkreis|Kreis) ", "", kv[1]["name"])))
    payload = {
        "_quelle": "© Statistisches Bundesamt (Destatis), Gemeindeverzeichnis GV100AD, Stand 31.03.2017, "
                   "Datenlizenz Deutschland – Namensnennung – Version 2.0",
        "laender": dict(sorted(result.items(), key=lambda kv: kv[1]["name"])),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n = sum(len(l["kreise"]) for l in result.values())
    print(f"{OUT} geschrieben: {len(result)} Länder, {n} Kreise, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
