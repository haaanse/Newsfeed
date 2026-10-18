"""Minimaler Ollama-Client (Embeddings und Chat). Alles bleibt auf deinem Server."""
from __future__ import annotations

import json
import logging

import httpx
import numpy as np

log = logging.getLogger(__name__)


class OllamaUnavailable(RuntimeError):
    pass


class Ollama:
    def __init__(self, cfg: dict, client: httpx.Client | None = None):
        o = cfg["ollama"]
        self.embed_model = o["embed_model"]
        self.llm_model = o["llm_model"]
        self.client = client or httpx.Client(base_url=o["url"], timeout=o["timeout_seconds"])

    def available_models(self) -> set[str]:
        try:
            r = self.client.get("/api/tags", timeout=5)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise OllamaUnavailable(f"Ollama nicht erreichbar: {e}") from e
        names = set()
        for m in r.json().get("models", []):
            names.add(m["name"])
            names.add(m["name"].split(":")[0])  # "llama3.1:latest" -> "llama3.1"
        return names

    def check(self, need_llm: bool = False) -> None:
        models = self.available_models()
        wanted = [self.embed_model] + ([self.llm_model] if need_llm else [])
        missing = [m for m in wanted if m not in models]
        if missing:
            raise OllamaUnavailable(f"Modell fehlt in Ollama: {', '.join(missing)} "
                                    f"(installieren mit: ollama pull {missing[0]})")

    def embed(self, texts: list[str]) -> np.ndarray:
        """Normalisierte Embeddings (float32), eine Zeile pro Text."""
        try:
            r = self.client.post("/api/embed", json={"model": self.embed_model, "input": texts})
            r.raise_for_status()
            vectors = r.json()["embeddings"]
        except httpx.HTTPError as e:
            raise OllamaUnavailable(f"Embedding fehlgeschlagen: {e}") from e
        arr = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return arr / np.where(norms == 0, 1, norms)

    def chat_json(self, system: str, user: str, max_tokens: int = 200) -> dict:
        """Antwort des LLM als JSON-Objekt (deterministisch, temperature 0)."""
        try:
            r = self.client.post("/api/chat", json={
                "model": self.llm_model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "format": "json",
                "stream": False,
                "options": {"temperature": 0, "num_predict": max_tokens},
            })
            r.raise_for_status()
            return json.loads(r.json()["message"]["content"])
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
            raise OllamaUnavailable(f"LLM-Anfrage fehlgeschlagen: {e}") from e
