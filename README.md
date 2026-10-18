# Newsfeed – privater News-Feed ohne Tracking

Selbstgehostete Alternative zum „Entdecken“-Feed: sammelt deutschsprachige
Nachrichten per RSS, sortiert sie nach Themen und zeigt sie in einer
installierbaren Web-App (PWA) auf PC und Android.

- **Kein Tracking:** keine Konten, keine Cookies, keine Zugriffs-Logs mit IP-Adressen,
  keine externen Skripte oder Schriften. Einstellungen bleiben im Browser des Geräts.
- **Rechtlich sparsam:** gespeichert werden nur Titel, kurzer Anrisstext aus dem Feed,
  Quelle, Zeit, Link und die Vorschaubild-URL des Feeds. Keine Volltexte, kein Scraping.
  Bilder werden nie auf dem Server gespeichert und sind standardmäßig **aus**.
- **Paywall-Artikel** werden ausgeblendet (Heuristik, anpassbar in `config/config.yaml`).

## Stand

| Schritt | Inhalt | Status |
|---|---|---|
| 1 | MVP: Fetcher, SQLite, API, PWA mit Themen-Tabs (chronologisch) | ✅ |
| 2 | Ollama: Story-Clustering, Ranking, Themenzuordnung, Regional (Land/Landkreis) | geplant |
| 3 | Themen ausblenden, kombinierter Feed, Einstellungen, Design-Feinschliff | geplant |

## Projektstruktur

```
config/config.yaml        Quellen, Themen, Paywall-Regeln, Intervalle  ← hier editieren
backend/app/              FastAPI-App (fetcher.py, api.py, main.py, db.py, config.py)
backend/tests/            automatische Tests mit Beispiel-Feeds
frontend/                 PWA (Vanilla JS, ohne Build-Schritt)
scripts/backup.ps1        Datenbank-Sicherung (Windows)
scripts/make_icons.py     erzeugt die Icons neu
Dockerfile, docker-compose.yml
```

---

## Start auf dem Windows-Server

Voraussetzungen: Docker Desktop (WSL2) und Git sind installiert.

```powershell
git clone https://github.com/haaanse/Newsfeed.git
cd Newsfeed
git checkout ccr-98f781c9-kxp4hq      # bis der Branch gemergt ist
docker compose up -d --build
```

Prüfen:

```powershell
docker compose ps                     # Status "healthy" nach ca. 30 s
docker compose logs -f                # "Abruf fertig: {... 'new_articles': ...}"
```

Im Browser **auf dem Server**: <http://localhost:8080>

### Quellen prüfen

Unter <http://localhost:8080/api/sources> steht für jede Quelle `error_count`,
`last_error` und die Anzahl der Artikel. Liefert eine Quelle dauerhaft Fehler
(z. B. `HTTP 404`), die URL in `config/config.yaml` korrigieren oder die Quelle
mit `enabled: false` pausieren. Die Änderung gilt ab dem nächsten Abruf, ohne Neustart.

Sofort einen Abruf auslösen:

```powershell
docker compose exec newsfeed python -m app.fetcher
```

### Autostart

Der Container hat `restart: unless-stopped`: Sobald Docker Desktop läuft, startet
der Newsfeed automatisch. Docker Desktop startet unter Windows erst **nach der
Anmeldung** (Docker Desktop → Settings → General → „Start Docker Desktop when you sign in“).

---

## HTTPS mit Tailscale (für Installation als App)

Die PWA lässt sich nur über HTTPS installieren. Mit Tailscale bekommst du ein
gültiges Zertifikat, ohne Domain und ohne Portfreigabe. Die App ist nur in deinem
privaten Tailnet erreichbar.

1. Tailscale auf dem **Server**, deinen **PCs** und **Android-Handys** installieren
   und überall mit demselben Konto anmelden (<https://tailscale.com/download>).
2. In der Admin-Konsole (<https://login.tailscale.com/admin/dns>):
   **MagicDNS** aktivieren und unter „HTTPS Certificates“ **Enable HTTPS** klicken.
3. Auf dem Server in einer PowerShell:
   ```powershell
   tailscale serve --bg 8080
   tailscale serve status
   ```
   Angezeigt wird die Adresse, z. B. `https://server.tailxxxx.ts.net`.
4. Diese Adresse auf dem Gerät öffnen:
   - **Chrome/Edge (PC):** Installieren-Symbol in der Adressleiste.
   - **Android (Chrome):** Menü ⋮ → „App installieren“.

`tailscale serve --bg` bleibt auch nach einem Neustart aktiv; Tailscale läuft unter
Windows als Dienst. Der Port 8080 ist nur auf `127.0.0.1` gebunden, ist also im
LAN nicht ohne Tailscale erreichbar.

---

## Bedienung

| Aktion | Handy | PC |
|---|---|---|
| Thema wechseln | Tab antippen oder links/rechts wischen | Seitenleiste, Tasten `1`–`9`, `[` / `]` |
| Durch Artikel | scrollen | `j` / `k`, Enter öffnet |
| Neu laden | ⟳ | `r` |
| Bilder an/aus | ⚙ Einstellungen | ⚙ Einstellungen |

Jeder Klick öffnet den Originalartikel beim Verlag (neuer Tab, ohne Referrer).
Offline zeigt die App den zuletzt geladenen Stand (nur Texte).

## Konfiguration

Alles steht in `config/config.yaml`, mit Kommentaren:

- `sources`: Feeds mit `publisher`, `topic`, `weight`, optional `enabled: false`
- `topics`: Themen und deren Reihenfolge
- `paywall`: Muster, an denen Bezahlartikel erkannt werden
- `fetch.interval_minutes`: Abrufintervall (Änderung braucht `docker compose restart`)
- `retention_days`: Aufbewahrung (Standard 14 Tage, Aufräumen täglich 03:30 UTC)

## Backup

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup.ps1
```

Legt `backups\newsfeed-<Datum>.db` an und behält die letzten 14 Sicherungen.
Die Datenbank liegt im Docker-Volume `newsfeed_newsfeed-data`.

## Update

```powershell
git pull
docker compose up -d --build
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
| `GET /api/topics` | Themen mit Artikelanzahl der letzten 48 h |
| `GET /api/articles?topics=tech,ki&limit=40&before=<cursor>` | Artikel, neueste zuerst |
| `GET /api/sources` | Status aller Quellen |
| `GET /api/health` | Lebenszeichen |
| `GET /api/docs` | interaktive API-Doku |
