#!/usr/bin/env python3
"""Session file uploads for Juno chat context."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
UPLOAD_ROOT = HQ / "memory" / "uploads"
ALLOWED_EXT = {
    ".txt", ".md", ".json", ".py", ".ts", ".tsx", ".js", ".jsx", ".html", ".htm",
    ".css", ".scss", ".csv", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log",
    ".vue", ".sql", ".rs", ".go", ".java", ".c", ".cpp", ".h", ".hpp", ".xml",
    ".env", ".sh", ".bat", ".ps1", ".dockerfile",
}
MAX_BYTES = 512_000
MAX_ATTACHMENTS = 8
MAX_INJECT_CHARS = 12_000


def _session_dir(session_id: str) -> Path:
    d = UPLOAD_ROOT / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_upload(session_id: str, filename: str, data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        return {"ok": False, "error": f"文件过大（上限 {MAX_BYTES // 1024}KB）"}
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return {"ok": False, "error": f"不支持的后缀 {ext}，仅支持文本类文件"}
    safe = re.sub(r"[^\w.\-]+", "_", Path(filename).name)[:120] or "upload.txt"
    uid = uuid.uuid4().hex[:8]
    dest = _session_dir(session_id) / f"{uid}_{safe}"
    dest.write_bytes(data)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        dest.unlink(missing_ok=True)
        return {"ok": False, "error": "无法解码为 UTF-8 文本"}
    item = {
        "id": uid,
        "name": safe,
        "path": str(dest.relative_to(HQ)).replace("\\", "/"),
        "size": len(data),
        "chars": len(text),
        "uploaded": datetime.now().isoformat(timespec="seconds"),
    }
    return {"ok": True, "attachment": item, "preview": text[:800]}


def merge_attachment(session: dict, item: dict) -> None:
    att = session.setdefault("attachments", [])
    att.append(item)
    session["attachments"] = att[-MAX_ATTACHMENTS:]


def format_attachments_for_prompt(session: dict) -> str:
    att = session.get("attachments") or []
    if not att:
        return ""
    lines = ["## 用户上传的文档（本轮上下文 · 优先参考）"]
    total = 0
    for i, a in enumerate(att, 1):
        fp = HQ / a.get("path", "")
        if not fp.is_file():
            continue
        text = fp.read_text(encoding="utf-8", errors="replace")
        if total + len(text) > MAX_INJECT_CHARS:
            text = text[: max(0, MAX_INJECT_CHARS - total)] + "\n…（截断）"
        lines.append(f"\n### 文档 {i} · `{a.get('name')}`\n```\n{text}\n```")
        total += len(text)
        if total >= MAX_INJECT_CHARS:
            break
    return "\n".join(lines) if len(lines) > 1 else ""


def read_attachment(session_id: str, att_id: str) -> dict:
    """Return attachment text for preview UI."""
    d = UPLOAD_ROOT / session_id
    if not d.is_dir():
        return {"ok": False, "error": "session not found"}
    for fp in d.iterdir():
        if not fp.name.startswith(f"{att_id}_"):
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return {"ok": False, "error": str(e)}
        return {
            "ok": True,
            "id": att_id,
            "name": fp.name.split("_", 1)[-1] if "_" in fp.name else fp.name,
            "path": str(fp.relative_to(HQ)).replace("\\", "/"),
            "content": text[:50000],
            "truncated": len(text) > 50000,
        }
    return {"ok": False, "error": "attachment not found"}


def attach_workspace_file(session_id: str, path_str: str) -> dict:
    """Attach a sandbox file or folder by path (drag / @path)."""
    import juno_tools

    juno_tools.set_session_context(session_id)
    # User explicitly attached → trust before resolve (covers D:/E: outside default broad roots)
    juno_tools.trust_user_path(path_str)
    fp = juno_tools._smart_resolve(path_str)
    if not fp:
        # Last chance: path exists on disk but was blocked — still trust & retry
        try:
            raw = Path((path_str or "").strip().strip('"').strip("'"))
            if raw.is_absolute() and raw.exists():
                juno_tools.trust_user_path(str(raw))
                fp = juno_tools._smart_resolve(path_str)
        except OSError:
            fp = None
    if not fp:
        return {"ok": False, "error": f"路径不可访问: {path_str}"}
    if fp.is_dir():
        return attach_folder(session_id, fp)
    result = juno_tools.probe_path(path_str)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "无法读取文件"}
    content = result.get("content")
    if not content:
        return {"ok": False, "error": "不是可读文本文件"}
    name = Path(path_str).name or "file.txt"
    return save_upload(session_id, name, content.encode("utf-8"))


def attach_folder(session_id: str, dir_path: Path, *, max_files: int = 30) -> dict:
    """Pack folder tree + text file snippets into one attachable document."""
    import juno_tools

    tree = juno_tools.list_dir_tree(str(dir_path), depth=3)
    parts = [
        f"# 文件夹 · `{dir_path}`",
        "",
        "## 目录结构",
        "```json",
        json.dumps(tree, ensure_ascii=False, indent=2)[:6000],
        "```",
        "",
        "## 文件内容（文本类 · 自动采样）",
    ]
    total_chars = sum(len(p) for p in parts)
    file_count = 0
    skip_dirs = juno_tools.SKIP_TREE_NAMES

    try:
        candidates = sorted(dir_path.rglob("*"), key=lambda p: (len(p.parts), str(p).lower()))
    except OSError as e:
        return {"ok": False, "error": str(e)}

    for fp in candidates:
        if file_count >= max_files or total_chars >= MAX_INJECT_CHARS - 2000:
            break
        if not fp.is_file():
            continue
        if any(part in skip_dirs for part in fp.parts):
            continue
        ext = fp.suffix.lower()
        if ext not in ALLOWED_EXT and ext != "":
            continue
        try:
            size = fp.stat().st_size
        except OSError:
            continue
        if size > 200_000:
            parts.append(f"\n### `{fp.relative_to(dir_path)}`（跳过，>{size // 1024}KB）")
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        chunk = text[:4000]
        rel = str(fp.relative_to(dir_path)).replace("\\", "/")
        block = f"\n### `{rel}`\n```\n{chunk}\n```"
        parts.append(block)
        total_chars += len(block)
        file_count += 1

    if file_count == 0:
        parts.append("\n（目录内无可读文本文件，Agent 可用 list_dir/glob 继续探索）")

    bundle = "\n".join(parts)
    if len(bundle.encode("utf-8")) > MAX_BYTES:
        bundle = bundle[: MAX_BYTES // 2] + "\n…（文件夹过大，已截断）"
    name = f"{dir_path.name}-folder.md"
    out = save_upload(session_id, name, bundle.encode("utf-8"))
    if out.get("ok"):
        out["attachment"]["kind"] = "folder"
        out["attachment"]["source_path"] = str(dir_path)
        out["preview"] = bundle[:1200]
    return out


def resolve_drop_folder(folder_name: str) -> dict:
    """Guess full path when browser drag omits file:// URI (common on Windows)."""
    import juno_tools

    name = (folder_name or "").strip()
    if not name:
        return {"ok": False, "error": "folder_name required"}

    matches: list[str] = []
    seen: set[str] = set()
    roots = juno_tools._broad_read_roots() + juno_tools._drive_roots()
    name_lower = name.lower()

    def add(p: Path) -> None:
        if not p.is_dir() or p.name.lower() != name_lower:
            return
        sp = str(p.resolve())
        if sp not in seen:
            seen.add(sp)
            matches.append(sp)

    for root in roots:
        if not root.is_dir():
            continue
        try:
            add(root / name)
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                add(child)
                add(child / name)
                try:
                    for sub in child.iterdir():
                        if sub.is_dir():
                            add(sub)
                except OSError:
                    pass
        except OSError:
            continue
        if len(matches) >= 12:
            break

    matches.sort(key=lambda x: (x.count("\\"), len(x)))
    if len(matches) == 1:
        return {"ok": True, "path": matches[0], "matches": matches}
    if matches:
        return {"ok": False, "matches": matches, "error": "ambiguous folder name"}
    return {"ok": False, "error": f"未找到文件夹 {name}"}
