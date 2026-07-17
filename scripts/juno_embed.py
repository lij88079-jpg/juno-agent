#!/usr/bin/env python3
"""Ollama embedding client for hybrid semantic search."""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
PROFILE = HQ / "config" / "agent-profile.json"
CACHE_DIR = HQ / "config" / "index" / "embed_cache"


def _cfg() -> dict:
    if PROFILE.exists():
        return json.loads(PROFILE.read_text(encoding="utf-8"))
    return {}


def embed_model() -> str:
    return (( _cfg().get("index") or {}).get("embedModel") or "nomic-embed-text:latest")


def embed_base() -> str:
    return ((_cfg().get("index") or {}).get("embedApiBase") or "http://127.0.0.1:11434").rstrip("/")


def is_available() -> bool:
    try:
        v = embed_text("ping", timeout=3)
        return bool(v)
    except Exception:
        return False


def embed_text(text: str, *, timeout: int = 8) -> list[float] | None:
    t = (text or "").strip()[:4000]
    if not t:
        return None
    payload = json.dumps({"model": embed_model(), "prompt": t}).encode("utf-8")
    req = urllib.request.Request(
        f"{embed_base()}/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        emb = data.get("embedding")
        return emb if isinstance(emb, list) and emb else None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _cache_path(chunk_id: int) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{chunk_id}.json"


def get_chunk_vector(chunk_id: int, text: str) -> list[float] | None:
    fp = _cache_path(chunk_id)
    if fp.exists():
        try:
            return json.loads(fp.read_text(encoding="utf-8")).get("v")
        except json.JSONDecodeError:
            pass
    v = embed_text(text[:900])
    if v:
        fp.write_text(json.dumps({"v": v}), encoding="utf-8")
    return v


def rerank(query: str, hits: list[dict], *, top_k: int = 6, alpha: float = 0.45) -> list[dict]:
    """Hybrid re-rank: alpha * TF-IDF norm + (1-alpha) * cosine."""
    if not hits:
        return []
    # Cap candidates — embedding each hit can stall Agent for minutes
    candidates = hits[: min(len(hits), max(top_k * 2, 8))]
    qv = embed_text(query, timeout=5)
    if not qv:
        return hits[:top_k]

    max_tf = max((h.get("score") or 0) for h in candidates) or 1.0
    scored: list[tuple[float, dict]] = []
    for h in candidates:
        cid = h.get("chunk_id")
        text = h.get("text") or ""
        tf_norm = (h.get("score") or 0) / max_tf
        cv = get_chunk_vector(int(cid), text) if cid is not None else embed_text(text[:900], timeout=5)
        cos = cosine(qv, cv) if cv else 0.0
        hybrid = alpha * tf_norm + (1 - alpha) * cos
        item = dict(h)
        item["score"] = round(hybrid, 4)
        item["embed"] = round(cos, 4)
        scored.append((hybrid, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in scored[:top_k]]
