"""Laden und Prüfen der YAML-Konfiguration (mit automatischem Neuladen)."""
from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "config.yaml"

_lock = threading.Lock()
_cache: dict = {"path": None, "mtime": None, "data": None}


def config_path() -> Path:
    return Path(os.environ.get("NEWSFEED_CONFIG", DEFAULT_CONFIG))


class ConfigError(ValueError):
    pass


def validate(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ConfigError("Konfiguration ist leer oder kein YAML-Objekt")

    topics = data.get("topics") or []
    topic_ids = [t.get("id") for t in topics]
    if not topic_ids or None in topic_ids:
        raise ConfigError("'topics' fehlt oder ein Thema hat keine 'id'")
    if len(set(topic_ids)) != len(topic_ids):
        raise ConfigError("Themen-IDs sind nicht eindeutig")
    for t in topics:
        t.setdefault("name", t["id"])

    sources = data.get("sources") or []
    seen = set()
    for s in sources:
        for key in ("id", "url", "publisher"):
            if not s.get(key):
                raise ConfigError(f"Quelle {s!r}: Feld '{key}' fehlt")
        if s["id"] in seen:
            raise ConfigError(f"Quellen-ID doppelt: {s['id']}")
        seen.add(s["id"])
        if s.get("topic") is not None and s["topic"] not in topic_ids:
            raise ConfigError(f"Quelle {s['id']}: unbekanntes Thema '{s['topic']}'")
        s.setdefault("name", s["publisher"])
        s["weight"] = float(s.get("weight", 1.0))
        s["enabled"] = bool(s.get("enabled", True))

    fetch = data.setdefault("fetch", {})
    fetch.setdefault("interval_minutes", 15)
    fetch.setdefault("timeout_seconds", 20)
    fetch.setdefault("max_workers", 8)
    fetch.setdefault("summary_max_chars", 300)
    fetch.setdefault("user_agent", "PrivateNewsfeed/0.1")
    data.setdefault("retention_days", 14)

    paywall = data.setdefault("paywall", {})
    paywall.setdefault("hide", True)
    for key in ("title_patterns", "url_patterns", "category_patterns"):
        try:
            paywall[f"_{key}"] = [re.compile(p, re.I) for p in paywall.get(key) or []]
        except re.error as e:
            raise ConfigError(f"paywall.{key}: ungültiger regulärer Ausdruck: {e}") from e

    rules = data.get("topic_rules") or {}
    compiled = {}
    for topic, patterns in rules.items():
        if topic not in topic_ids:
            raise ConfigError(f"topic_rules: unbekanntes Thema '{topic}'")
        try:
            compiled[topic] = [re.compile(p) for p in patterns or []]
        except re.error as e:
            raise ConfigError(f"topic_rules.{topic}: ungültiger regulärer Ausdruck: {e}") from e
    data["_topic_rules"] = compiled

    ollama = data.setdefault("ollama", {})
    ollama["url"] = os.environ.get("OLLAMA_URL") or ollama.get("url") or "http://localhost:11434"
    ollama.setdefault("embed_model", "nomic-embed-text")
    ollama.setdefault("llm_model", "llama3.1")
    ollama.setdefault("timeout_seconds", 180)
    ollama.setdefault("batch_size", 32)
    ollama.setdefault("cluster_threshold", 0.80)
    ollama.setdefault("cluster_window_hours", 48)
    classify = ollama.setdefault("classify", {})
    classify.setdefault("from_topics", ["top"])
    classify.setdefault("neighbors", 9)
    classify.setdefault("min_similarity", 0.62)
    classify.setdefault("min_share", 0.4)
    classify.setdefault("llm_fallback", False)
    classify.setdefault("llm_max_per_run", 10)
    summaries = ollama.setdefault("summaries", {})
    summaries.setdefault("enabled", False)
    summaries.setdefault("min_sources", 3)
    summaries.setdefault("max_per_run", 3)

    from .ranking import Formula, FormulaError  # noqa: PLC0415 – vermeidet Importzyklus
    ranking = data.setdefault("ranking", {})
    ranking.setdefault("formula", "1.2 * log2(1 + sources) + 2.0 * 0.5 ** (age_hours / 8) + 0.6 * weight")
    ranking.setdefault("window_hours", 48)
    try:
        ranking["_formula"] = Formula(ranking["formula"], ranking.get("constants"))
    except FormulaError as e:
        raise ConfigError(str(e)) from e

    regional = data.setdefault("regional", {})
    regional.setdefault("keep_days", 14)
    extra = regional.get("extra_sources") or {}
    for land, items in extra.items():
        for s in items or []:
            for key in ("id", "url", "publisher"):
                if not s.get(key):
                    raise ConfigError(f"regional.extra_sources.{land}: Feld '{key}' fehlt")
    regional["extra_sources"] = extra
    return data


def load_config(path: Path | None = None) -> dict:
    """Liest die Konfiguration; bei Dateiänderung neu. Bei Fehlern bleibt die alte aktiv."""
    path = Path(path) if path else config_path()
    with _lock:
        mtime = path.stat().st_mtime
        if _cache["path"] == path and _cache["mtime"] == mtime:
            return _cache["data"]
        try:
            with open(path, encoding="utf-8") as f:
                data = validate(yaml.safe_load(f))
        except (ConfigError, yaml.YAMLError) as e:
            if _cache["path"] == path and _cache["data"] is not None:
                log.error("Konfiguration fehlerhaft, verwende vorherige Version: %s", e)
                return _cache["data"]
            raise
        _cache.update(path=path, mtime=mtime, data=data)
        log.info("Konfiguration geladen: %d Themen, %d Quellen",
                 len(data["topics"]), len(data["sources"]))
        return data
