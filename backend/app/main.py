"""FastAPI-App: API unter /api, PWA unter /, Feed-Abruf per APScheduler."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import api, db, enrich, fetcher
from .config import ROOT, load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("newsfeed")
logging.getLogger("httpx").setLevel(logging.WARNING)

FRONTEND = ROOT / "frontend"

SECURITY_HEADERS = {
    # Nur eigene Skripte/Styles; Bilder dürfen (nur wenn eingeschaltet) von https-Quellen kommen.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' https: data:; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Permissions-Policy": "interest-cohort=(), browsing-topics=(), geolocation=(), camera=(), microphone=()",
}


def cycle() -> None:
    """Ein Durchlauf: Feeds abrufen, dann per Ollama anreichern."""
    try:
        fetcher.run_fetch()
    finally:
        enrich.run()


def _start_scheduler() -> BackgroundScheduler:
    cfg = load_config()
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(cycle, "interval", minutes=cfg["fetch"]["interval_minutes"],
                  id="fetch", next_run_time=datetime.now(timezone.utc),
                  max_instances=1, coalesce=True)
    sched.add_job(fetcher.cleanup, "cron", hour=3, minute=30, id="cleanup")
    sched.start()
    log.info("Scheduler gestartet: Abruf alle %d Minuten", cfg["fetch"]["interval_minutes"])
    return sched


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    sched = None if os.environ.get("NEWSFEED_DISABLE_SCHEDULER") else _start_scheduler()
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="Newsfeed", lifespan=lifespan, docs_url="/api/docs", redoc_url=None,
              openapi_url="/api/openapi.json")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    path = request.url.path
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif path in ("/", "/index.html", "/sw.js", "/manifest.webmanifest"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.include_router(api.router, prefix="/api")
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
