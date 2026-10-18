"""RSS/Atom-Abruf: lädt Feeds, bereinigt Einträge und speichert sie.

Es werden ausschließlich Titel, kurzer Anrisstext, Quelle, Zeit, Link und
die vom Feed gelieferte Vorschaubild-URL gespeichert – keine Volltexte,
kein Abruf der Artikelseiten, keine Bilddateien.
"""
from __future__ import annotations

import calendar
import html
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx

from . import db
from .config import load_config

log = logging.getLogger(__name__)

MAX_FEED_BYTES = 5 * 1024 * 1024
TRACKING_PARAMS = re.compile(r"^(utm_\w+|wt_\w+|wt_mc|ref|cid|xtor|at_\w+|fbclid|gclid|mc_\w+)$", re.I)


# ---------------------------------------------------------------------------
# Text- und URL-Bereinigung
# ---------------------------------------------------------------------------
class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.first_img: str | None = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "img" and self.first_img is None:
            self.first_img = dict(attrs).get("src")
        elif tag in ("br", "p", "div", "li"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _parse_html(raw: str) -> _TextExtractor:
    p = _TextExtractor()
    p.feed(raw or "")
    p.close()
    return p


def clean_text(raw: str | None) -> str:
    """HTML entfernen, Entities auflösen, Leerraum normalisieren."""
    if not raw:
        return ""
    text = "".join(_parse_html(raw).parts)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-–")
    return cut + " …"


def normalize_url(url: str) -> str:
    """Tracking-Parameter und Fragment entfernen, damit Duplikate erkannt werden."""
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not TRACKING_PARAMS.match(k)])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))


def _is_http(url: str | None) -> bool:
    return bool(url) and urlsplit(url).scheme in ("http", "https")


# ---------------------------------------------------------------------------
# Einträge auswerten
# ---------------------------------------------------------------------------
def extract_image(entry) -> str | None:
    """Nur Bild-URLs, die der Feed selbst liefert (https), nie heruntergeladen."""
    candidates: list[str] = []
    for m in entry.get("media_thumbnail") or []:
        candidates.append(m.get("url"))
    for m in entry.get("media_content") or []:
        if m.get("medium") == "image" or (m.get("type") or "").startswith("image/"):
            candidates.append(m.get("url"))
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and (link.get("type") or "").startswith("image/"):
            candidates.append(link.get("href"))
    for enc in entry.get("enclosures") or []:
        if (enc.get("type") or "").startswith("image/"):
            candidates.append(enc.get("href") or enc.get("url"))
    # Fallback: erstes <img> im Anrisstext bzw. Content des Feeds
    for raw in [entry.get("summary")] + [c.get("value") for c in entry.get("content") or []]:
        if raw and "<img" in raw:
            candidates.append(_parse_html(raw).first_img)
    for url in candidates:
        if url and urlsplit(url).scheme == "https":
            return html.unescape(url)
    return None


def is_paywalled(entry, title: str, url: str, paywall_cfg: dict) -> bool:
    if any(p.search(title) for p in paywall_cfg.get("_title_patterns", [])):
        return True
    if any(p.search(url) for p in paywall_cfg.get("_url_patterns", [])):
        return True
    terms = [(t.get("term") or "").strip() for t in entry.get("tags") or []]
    return any(p.search(term) for term in terms for p in paywall_cfg.get("_category_patterns", []))


def entry_timestamp(entry, now: int) -> int:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        st = entry.get(key)
        if st:
            ts = calendar.timegm(st)
            return min(ts, now)  # Zukunftsdaten (falsche Zeitzonen) abschneiden
    return now


@dataclass
class Item:
    url: str
    title: str
    summary: str
    image_url: str | None
    published_at: int
    paywall: bool


def parse_feed(content: bytes, cfg: dict, now: int | None = None) -> list[Item]:
    now = now or int(time.time())
    parsed = feedparser.parse(content)
    max_chars = cfg["fetch"]["summary_max_chars"]
    items: list[Item] = []
    for entry in parsed.entries:
        link = entry.get("link")
        title = clean_text(entry.get("title"))
        if not title or not _is_http(link):
            continue
        url = normalize_url(link)
        summary = truncate(clean_text(entry.get("summary")), max_chars)
        if summary == title:
            summary = ""
        items.append(Item(
            url=url,
            title=title,
            summary=summary,
            image_url=extract_image(entry),
            published_at=entry_timestamp(entry, now),
            paywall=is_paywalled(entry, title, url, cfg["paywall"]),
        ))
    if not items and parsed.bozo:
        raise ValueError(f"Kein gültiger Feed: {parsed.bozo_exception}")
    return items


# ---------------------------------------------------------------------------
# Abruf
# ---------------------------------------------------------------------------
@dataclass
class FetchResult:
    source_id: str
    status: str                    # ok | not_modified | error
    content: bytes | None = None
    etag: str | None = None
    last_modified: str | None = None
    error: str | None = None


def fetch_source(client: httpx.Client, source: dict, etag: str | None, last_modified: str | None) -> FetchResult:
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        with client.stream("GET", source["url"], headers=headers) as r:
            if r.status_code == 304:
                return FetchResult(source["id"], "not_modified", etag=etag, last_modified=last_modified)
            if r.status_code >= 400:
                return FetchResult(source["id"], "error", error=f"HTTP {r.status_code}")
            chunks, size = [], 0
            for chunk in r.iter_bytes():
                size += len(chunk)
                if size > MAX_FEED_BYTES:
                    return FetchResult(source["id"], "error", error="Feed größer als 5 MB")
                chunks.append(chunk)
            return FetchResult(source["id"], "ok", content=b"".join(chunks),
                               etag=r.headers.get("etag"), last_modified=r.headers.get("last-modified"))
    except httpx.HTTPError as e:
        return FetchResult(source["id"], "error", error=f"{type(e).__name__}: {e}"[:300])


def sync_sources(conn, cfg: dict) -> None:
    """Quellen aus der YAML-Datei in die Datenbank übernehmen."""
    ids = [s["id"] for s in cfg["sources"]]
    for s in cfg["sources"]:
        conn.execute(
            """INSERT INTO sources (id, name, publisher, url, topic, weight)
               VALUES (:id, :name, :publisher, :url, :topic, :weight)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, publisher=excluded.publisher, topic=excluded.topic,
                 weight=excluded.weight,
                 etag=CASE WHEN sources.url = excluded.url THEN sources.etag END,
                 last_modified=CASE WHEN sources.url = excluded.url THEN sources.last_modified END,
                 url=excluded.url""",
            {"topic": None, **s},
        )
    conn.execute(f"DELETE FROM sources WHERE id NOT IN ({','.join('?' * len(ids))})", ids)


def store_items(conn, source: dict, items: list[Item], now: int) -> int:
    new = 0
    for it in items:
        cur = conn.execute(
            """INSERT INTO articles (url, title, summary, image_url, source_id, publisher,
                                     published_at, fetched_at, paywall)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(url) DO NOTHING""",
            (it.url, it.title, it.summary, it.image_url, source["id"], source["publisher"],
             it.published_at, now, int(it.paywall)),
        )
        if cur.rowcount:
            new += 1
            article_id = cur.lastrowid
        else:
            article_id = conn.execute("SELECT id FROM articles WHERE url = ?", (it.url,)).fetchone()[0]
        if source.get("topic"):
            conn.execute("INSERT OR IGNORE INTO article_topics (article_id, topic) VALUES (?, ?)",
                         (article_id, source["topic"]))
    return new


def run_fetch(cfg: dict | None = None, db_file: Path | None = None,
              client: httpx.Client | None = None) -> dict:
    """Ein kompletter Abruf aller aktiven Quellen. Gibt eine Zusammenfassung zurück."""
    cfg = cfg or load_config()
    started = time.time()
    sources = [s for s in cfg["sources"] if s["enabled"]]
    with db.connect(db_file) as conn:
        sync_sources(conn, cfg)
        state = {r["id"]: (r["etag"], r["last_modified"])
                 for r in conn.execute("SELECT id, etag, last_modified FROM sources")}

    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=cfg["fetch"]["timeout_seconds"], follow_redirects=True,
                              headers={"User-Agent": cfg["fetch"]["user_agent"]})
    try:
        with ThreadPoolExecutor(max_workers=cfg["fetch"]["max_workers"]) as pool:
            results = list(pool.map(lambda s: fetch_source(client, s, *state.get(s["id"], (None, None))),
                                    sources))
    finally:
        if own_client:
            client.close()

    now = int(time.time())
    summary = {"sources": len(sources), "ok": 0, "not_modified": 0, "errors": 0, "new_articles": 0}
    by_id = {s["id"]: s for s in sources}
    with db.connect(db_file) as conn:
        for res in results:
            source = by_id[res.source_id]
            if res.status == "ok":
                try:
                    items = parse_feed(res.content, cfg, now)
                except Exception as e:  # noqa: BLE001 – ein kaputter Feed darf den Lauf nicht stoppen
                    res = FetchResult(res.source_id, "error", error=f"Parser: {e}"[:300])
            if res.status == "error":
                summary["errors"] += 1
                conn.execute("""UPDATE sources SET last_fetch=?, error_count=error_count+1, last_error=?
                                WHERE id=?""", (now, res.error, res.source_id))
                log.warning("Feed %s: %s", res.source_id, res.error)
                continue
            new = store_items(conn, source, items, now) if res.status == "ok" else 0
            summary[res.status] += 1
            summary["new_articles"] += new
            conn.execute("""UPDATE sources SET last_fetch=?, last_ok=?, error_count=0, last_error=NULL,
                              etag=?, last_modified=?, last_new=? WHERE id=?""",
                         (now, now, res.etag, res.last_modified, new, res.source_id))
    summary["seconds"] = round(time.time() - started, 1)
    log.info("Abruf fertig: %s", summary)
    return summary


def cleanup(cfg: dict | None = None, db_file: Path | None = None, now: int | None = None) -> int:
    """Artikel löschen, die älter als retention_days sind."""
    cfg = cfg or load_config()
    cutoff = (now or int(time.time())) - int(cfg["retention_days"]) * 86400
    with db.connect(db_file) as conn:
        deleted = conn.execute("DELETE FROM articles WHERE published_at < ?", (cutoff,)).rowcount
    log.info("Aufräumen: %d alte Artikel gelöscht", deleted)
    return deleted


if __name__ == "__main__":  # manueller Abruf: python -m app.fetcher
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    db.init_db()
    print(run_fetch())
