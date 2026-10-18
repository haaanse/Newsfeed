# Newsfeed – privater News-Feed ohne Tracking

Selbstgehostete Alternative zum „Entdecken“-Feed: sammelt deutschsprachige Nachrichten per RSS,
erkennt gleiche Storys über mehrere Verlage hinweg (Ollama), rankt sie nach neutralen Signalen und
zeigt sie in einer installierbaren Web-App (PWA) auf PC und Android.

- **Kein Tracking:** keine Konten, keine Cookies, keine Zugriffs-Logs mit IP-Adressen, keine externen
  Skripte oder Schriften. Alle Einstellungen bleiben im Browser des jeweiligen Geräts.
- **Neutrales Ranking:** Anzahl unterschiedlicher Verlage + Aktualität + Quellengewicht; die Formel
  steht in `config/config.yaml`.
- **Rechtlich sparsam:** gespeichert werden nur Titel, kurzer Anrisstext aus dem Feed, Quelle, Zeit,
  Link und die Vorschaubild-URL des Feeds. Keine Volltexte, kein Scraping. Bilder werden nie auf dem
  Server gespeichert und sind standardmäßig **aus**. Ein Klick öffnet immer den Originalartikel.
- **Paywall-Artikel** werden ausgeblendet (Heuristik, anpassbar).

## Funktionen

| Bereich | Was es kann |
|---|---|
| Abruf | ~40 deutschsprachige Quellen, alle 15 Minuten, ETag/Last-Modified, Fehlerstatus pro Quelle |
| Storys | Gleiche Meldungen verschiedener Verlage werden per Embedding (`nomic-embed-text`) zu einer Story gruppiert (48-h-Fenster) |
| Themen | Feed-Thema + Regeln (z. B. alles mit „KI“ zusätzlich im KI-Tab) + automatische Zuordnung von Artikeln aus allgemeinen Feeds |
| Ranking | „Top“ (Formel) oder „Neueste“, umschaltbar |
| Überblick | optional ein neutraler Ein-Satz-Überblick pro Story per `llama3.1` (auf CPU standardmäßig aus) |
| Mein Feed | beliebige Themen zu einem gemeinsamen Feed zusammenführen |
| Filter | Themen ausblenden, Begriffe ausblenden (nur lokal), nur Lokalmeldungen |
| Regional | Bundesland + Landkreis wählbar; ein Land wird erst abgerufen, wenn es jemand wählt |
| App | PWA für Chrome/Edge und Android, Offline-Ansicht, Touch (Wischen), Maus und Tastatur |

Ohne Ollama läuft alles weiter – nur ohne Story-Gruppierung und automatische Themenzuordnung.

## Projektstruktur

```
config/config.yaml           Quellen, Themen, Ranking, Ollama, Regional, Paywall  ← hier editieren
backend/app/
  fetcher.py                 RSS-Abruf und Speicherung
  enrich.py, ollama.py       Embeddings, Clustering, Themenzuordnung, Überblick
  stories.py, ranking.py     Storys bauen und ranken (sichere Formel-Auswertung)
  regions.py, data/          Bundesländer, Kreise, Ortsnamen (Destatis)
  api.py, main.py            REST-API und Zeitsteuerung
  inspect_clusters.py        Hilfe beim Einstellen der Story-Gruppierung
backend/tests/               automatische Tests (Beispiel-Feeds, simuliertes Ollama)
frontend/                    PWA (Vanilla JS, ohne Build-Schritt)
scripts/                     Backup (Windows), Icons, Regionaldaten
```

---

## Einrichtung auf dem Windows-Server

### 1. Ollama-Modelle

In einer PowerShell auf dem Server:

```powershell
ollama pull nomic-embed-text      # Pflicht für Story-Gruppierung (klein, schnell auf CPU)
ollama pull llama3.1              # nur für optionalen Überblick / LLM-Themenzuordnung
```

### 2. Newsfeed starten

Voraussetzungen: Docker Desktop (WSL2) und Git.

```powershell
git clone https://github.com/haaanse/Newsfeed.git
cd Newsfeed
git checkout ccr-98f781c9-kxp4hq      # bis der Branch gemergt ist
docker compose up -d --build
```

Prüfen:

```powershell
docker compose ps                     # Status "healthy" nach ca. 30 s
docker compose logs -f                # "Abruf fertig ..." und "Anreicherung fertig ..."
```

Im Browser **auf dem Server**: <http://localhost:8080>

Steht im Log `Anreicherung übersprungen: Ollama nicht erreichbar`, erreicht der Container Ollama
nicht. Dann in Windows die Umgebungsvariable `OLLAMA_HOST` auf `0.0.0.0` setzen
(Systemsteuerung → Umgebungsvariablen), Ollama neu starten und testen. Ollama ist dann auch im
Heimnetz erreichbar – die Windows-Firewall sollte Port 11434 nur für vertrauenswürdige Netze zulassen.

```powershell
docker compose exec newsfeed python -c "import httpx; print(httpx.get('http://host.docker.internal:11434/api/tags').text)"
```

### 3. Quellen prüfen

<http://localhost:8080/api/sources> zeigt pro Quelle `error_count`, `last_error` und die Anzahl der
Artikel. Dauerhaft fehlerhafte Feeds in `config/config.yaml` korrigieren oder mit `enabled: false`
pausieren – wirkt ab dem nächsten Abruf, ohne Neustart.

Sofort abrufen (inkl. Anreicherung):

```powershell
docker compose exec newsfeed python -m app.fetcher
```

### 4. Story-Gruppierung einstellen (einmalig nach 1–2 Tagen)

```powershell
docker compose exec newsfeed python -m app.inspect_clusters
```

zeigt die größten Storys mit ihren Artikeln. Landen fremde Meldungen in einer Story,
`ollama.cluster_threshold` erhöhen (z. B. 0.84); werden gleiche Meldungen nicht zusammengefasst,
senken (z. B. 0.76). Danach mit `python -m app.inspect_clusters --reset` neu gruppieren lassen.

### 5. Autostart

Der Container hat `restart: unless-stopped`: Sobald Docker Desktop läuft, startet der Newsfeed
automatisch. Docker Desktop startet unter Windows erst **nach der Anmeldung**
(Docker Desktop → Settings → General → „Start Docker Desktop when you sign in“).

---

## HTTPS mit Tailscale (für Installation als App)

Die PWA lässt sich nur über HTTPS installieren. Mit Tailscale gibt es ein gültiges Zertifikat ohne
Domain und ohne Portfreigabe; die App ist nur in deinem privaten Tailnet erreichbar.

1. Tailscale auf **Server**, **PCs** und **Android-Handys** installieren, überall mit demselben Konto
   anmelden (<https://tailscale.com/download>).
2. In der Admin-Konsole (<https://login.tailscale.com/admin/dns>) **MagicDNS** aktivieren und unter
   „HTTPS Certificates“ **Enable HTTPS** klicken.
3. Auf dem Server:
   ```powershell
   tailscale serve --bg 8080
   tailscale serve status            # zeigt z. B. https://server.tailxxxx.ts.net
   ```
4. Adresse auf dem Gerät öffnen und installieren:
   **Chrome/Edge:** Installieren-Symbol in der Adressleiste · **Android:** Menü ⋮ → „App installieren“.

`tailscale serve --bg` bleibt nach Neustarts aktiv (Tailscale läuft als Windows-Dienst). Port 8080 ist
nur an `127.0.0.1` gebunden und im LAN ohne Tailscale nicht erreichbar.

---

## Bedienung

| Aktion | Handy | PC |
|---|---|---|
| Thema wechseln | Tab antippen oder links/rechts wischen | Seitenleiste, `1`–`9`, `[` / `]` |
| Top / Neueste | Umschalter oben | Umschalter oder `s` |
| Durch Storys | scrollen | `j` / `k`, `Enter` öffnet, `o` klappt weitere Quellen auf |
| Neu laden | ⟳ | `r` |
| Einstellungen | Regler-Symbol | Regler-Symbol oder `,` |

**Einstellungen** (nur auf dem Gerät gespeichert): Themen anzeigen/ausblenden, Themen für „Mein Feed“,
Region (Bundesland, Landkreis, nur Lokalmeldungen), Begriffe ausblenden, Vorschaubilder,
KI-Überblick, kompakte Ansicht, alles zurücksetzen.

## Konfiguration (`config/config.yaml`)

| Abschnitt | Inhalt |
|---|---|
| `sources` | Feeds mit `publisher`, `topic`, `weight`, optional `enabled: false` |
| `topics` | Themen und Reihenfolge |
| `topic_rules` | Muster, die einem Artikel zusätzlich ein Thema geben (z. B. KI) |
| `ranking.formula` | Ranking-Formel; Variablen `sources`, `articles`, `age_hours`, `update_hours`, `weight`, `max_weight`, `local` |
| `ollama` | Modelle, Gruppierungs-Schwelle, Themenzuordnung, Überblick (`summaries.enabled`) |
| `regional` | Aufbewahrung gewählter Länder, zusätzliche Regionalfeeds pro Land |
| `paywall` | Muster für Bezahlartikel |
| `fetch`, `retention_days` | Abrufintervall (Änderung: `docker compose restart`), Aufbewahrung (14 Tage) |

Beispiel Ranking – Aktualität stärker gewichten:

```yaml
ranking:
  formula: "1.0 * log2(1 + sources) + 3.0 * 0.5 ** (age_hours / half_life) + 0.5 * weight + local"
  constants: { half_life: 6 }
```

## Backup und Update

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup.ps1     # -> backups\newsfeed-<Datum>.db
git pull
docker compose up -d --build                                     # Datenbank wird automatisch migriert
```

## Entwicklung und Tests

```bash
cd backend
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload --port 8080
```

## API

| Endpunkt | Beschreibung |
|---|---|
| `GET /api/feed?topics=tech,ki&sort=top\|latest&limit=30&offset=0` | Storys; für Regional zusätzlich `land=BY&kreis=09187&only_local=true` |
| `GET /api/topics` | Themen mit Artikelanzahl der letzten 48 h |
| `GET /api/regions` | Bundesländer und Kreise |
| `GET /api/sources` | Status aller Quellen |
| `GET /api/health` | Lebenszeichen |
| `GET /api/docs` | interaktive API-Doku |

## Datenquellen und Lizenzen

- Ortsdaten: © Statistisches Bundesamt (Destatis), Gemeindeverzeichnis GV100AD, Stand 31.03.2017,
  [Datenlizenz Deutschland – Namensnennung – 2.0](https://www.govdata.de/dl-de/by-2-0),
  aufbereitet über das npm-Paket `gemeindeverzeichnis` (MIT). Neu erzeugen: `scripts/build_regions.py`.
- Nachrichteninhalte gehören den jeweiligen Verlagen; die App zeigt nur, was deren RSS-Feeds
  bereitstellen, und verlinkt immer auf das Original.
