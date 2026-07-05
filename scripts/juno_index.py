#!/usr/bin/env python3
"""Lightweight repo + knowledge indexer (TF-IDF, stdlib only)."""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
PROFILE = HQ / "config" / "agent-profile.json"
INDEX_DIR = HQ / "config" / "index"
CHUNKS_FILE = INDEX_DIR / "chunks.json"
STATS_FILE = INDEX_DIR / "stats.json"

TEXT_EXT = {
    ".md", ".txt", ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".html",
    ".css", ".scss", ".yaml", ".yml", ".toml", ".sql", ".sh", ".bat", ".ps1",
    ".vue", ".go", ".rs", ".java", ".kt", ".cs", ".cpp", ".h", ".xml", ".svg",
}


def load_profile() -> dict:
    if PROFILE.exists():
        return json.loads(PROFILE.read_text(encoding="utf-8"))
    return {}


def _tokenize(text: str) -> list[str]:
    parts = re.findall(r"[\u4e00-\u9fff]{1,8}|[a-zA-Z_][a-zA-Z0-9_./-]{1,48}|\d+", text.lower())
    stop = {"the", "and", "for", "that", "this", "with", "from", "import", "return", "const", "function"}
    return [p for p in parts if p not in stop and len(p) > 1]


def _should_skip(path: Path, cfg: dict) -> bool:
    ignore_dirs = set(cfg.get("ignoreDirs") or [])
    if any(part in ignore_dirs for part in path.parts):
        return True
    if path.suffix.lower() in set(cfg.get("ignoreExtensions") or []):
        return True
    return False


def _iter_files(cfg: dict) -> list[Path]:
    index_cfg = cfg.get("index") or {}
    roots: list[Path] = []
    for item in index_cfg.get("roots") or []:
        p = Path(item.get("path", ""))
        if p.exists():
            roots.append(p.resolve())
    for rel in index_cfg.get("extraPaths") or []:
        p = (HQ / rel).resolve()
        if p.exists():
            roots.append(p)
    if not roots:
        roots.append(HQ.resolve())

    max_bytes = int(index_cfg.get("maxFileBytes") or 524288)
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        if root.is_file():
            files = [root]
        else:
            files = root.rglob("*")
        for fp in files:
            if not fp.is_file():
                continue
            if _should_skip(fp, index_cfg):
                continue
            if fp.suffix.lower() not in TEXT_EXT and fp.suffix:
                continue
            try:
                if fp.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue
            key = str(fp.resolve())
            if key in seen:
                continue
            seen.add(key)
            out.append(fp.resolve())
    return out


def _chunk_text(text: str, chunk_chars: int) -> list[str]:
    if len(text) <= chunk_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_chars)
        if end < len(text):
            cut = text.rfind("\n", start, end)
            if cut > start + chunk_chars // 3:
                end = cut
        chunks.append(text[start:end])
        start = end
    return chunks


def build_index(*, force: bool = False) -> dict:
    cfg = load_profile()
    index_cfg = cfg.get("index") or {}
    chunk_chars = int(index_cfg.get("chunkChars") or 900)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    chunks: list[dict] = []
    doc_freq: Counter[str] = Counter()
    chunk_id = 0

    for fp in _iter_files(cfg):
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(fp)
        try:
            rel = str(fp.relative_to(HQ)).replace("\\", "/")
        except ValueError:
            rel = str(fp)
        for i, piece in enumerate(_chunk_text(text, chunk_chars)):
            tokens = _tokenize(piece)
            if not tokens:
                continue
            tf = Counter(tokens)
            for tok in tf:
                doc_freq[tok] += 1
            chunks.append(
                {
                    "id": chunk_id,
                    "path": rel,
                    "chunk": i,
                    "text": piece.strip(),
                    "tf": dict(tf),
                    "len": len(tokens),
                }
            )
            chunk_id += 1

    n_docs = max(len(chunks), 1)
    stats = {
        "built": datetime.now().isoformat(timespec="seconds"),
        "chunks": len(chunks),
        "files": len(_iter_files(cfg)),
        "doc_freq": dict(doc_freq),
        "n_docs": n_docs,
    }
    CHUNKS_FILE.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "chunks": len(chunks), "files": stats["files"], "built": stats["built"]}


def _load_index() -> tuple[list[dict], dict]:
    if not CHUNKS_FILE.exists() or not STATS_FILE.exists():
        build_index()
    chunks = json.loads(CHUNKS_FILE.read_text(encoding="utf-8"))
    stats = json.loads(STATS_FILE.read_text(encoding="utf-8"))
    return chunks, stats


def search(query: str, *, top_k: int | None = None) -> list[dict]:
    cfg = load_profile()
    k = top_k or int((cfg.get("index") or {}).get("topK") or 6)
    chunks, stats = _load_index()
    q_tf = Counter(_tokenize(query))
    if not q_tf or not chunks:
        return []

    doc_freq = stats.get("doc_freq") or {}
    n_docs = max(int(stats.get("n_docs") or len(chunks)), 1)
    scored: list[tuple[float, dict]] = []

    for ch in chunks:
        tf = ch.get("tf") or {}
        score = 0.0
        for tok, qf in q_tf.items():
            if tok not in tf:
                continue
            df = doc_freq.get(tok, 0)
            idf = math.log(1 + n_docs / (1 + df))
            score += (1 + math.log(1 + tf[tok])) * idf * qf
        if score > 0:
            scored.append((score, ch))

    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, ch in scored[: max(k * 5, 30)]:
        out.append(
            {
                "score": round(score, 4),
                "path": ch.get("path"),
                "chunk": ch.get("chunk"),
                "chunk_id": ch.get("id"),
                "text": (ch.get("text") or "")[:1200],
            }
        )

    index_cfg = cfg.get("index") or {}
    if index_cfg.get("hybridEmbed") is not False and out:
        try:
            import juno_embed
            if juno_embed.is_available():
                alpha = float(index_cfg.get("hybridAlpha") or 0.45)
                out = juno_embed.rerank(query, out, top_k=k, alpha=alpha)
                return out
        except Exception:
            pass
    return out[:k]


def format_context(query: str, *, top_k: int | None = None) -> str:
    hits = search(query, top_k=top_k)
    if not hits:
        return ""
    lines = ["## 检索到的代码/知识片段（仅供回答参考，勿编造未出现的内容）"]
    for i, h in enumerate(hits, 1):
        lines.append(f"\n### [{i}] `{h['path']}` (chunk {h['chunk']}, score {h['score']})\n```\n{h['text']}\n```")
    return "\n".join(lines)


def index_status() -> dict:
    if not STATS_FILE.exists():
        return {"built": None, "chunks": 0, "files": 0, "hybrid": False}
    stats = json.loads(STATS_FILE.read_text(encoding="utf-8"))
    hybrid = False
    try:
        import juno_brain
        st = juno_brain.check_ollama()
        cfg = load_profile()
        model = ((cfg.get("index") or {}).get("embedModel") or "nomic-embed").lower()
        hybrid = any(model.split(":")[0] in (m or "").lower() for m in (st.get("models") or []))
    except Exception:
        pass
    return {
        "built": stats.get("built"),
        "chunks": stats.get("chunks", 0),
        "files": stats.get("files", 0),
        "hybrid": hybrid,
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "search":
        q = " ".join(sys.argv[2:]) or "juno"
        print(json.dumps(search(q), ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "status":
        print(json.dumps(index_status(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(build_index(force=True), ensure_ascii=False, indent=2))
