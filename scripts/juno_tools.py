#!/usr/bin/env python3
"""Sandboxed tools for Juno Agent mode (read / search / limited shell)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
PROFILE = HQ / "config" / "agent-profile.json"
_READONLY = False
_PLAN_MODE = False
WRITE_TOOLS = {"write_file", "str_replace", "apply_patch", "delete_file", "git", "run_shell", "todo"}
PLAN_BLOCKED = {"write_file", "str_replace", "apply_patch", "delete_file", "git", "run_shell"}


def set_readonly(enabled: bool = True) -> None:
    global _READONLY
    _READONLY = enabled


def set_plan_mode(enabled: bool = True) -> None:
    global _PLAN_MODE
    _PLAN_MODE = enabled


def is_plan_mode() -> bool:
    return _PLAN_MODE


def is_readonly() -> bool:
    return _READONLY


def load_profile() -> dict:
    if PROFILE.exists():
        return json.loads(PROFILE.read_text(encoding="utf-8"))
    return {}


def resolve_profile_path(raw: str) -> Path:
    """Resolve agent-profile path entries relative to Juno HQ."""
    text = (raw or "").strip()
    if not text or text in {".", "./", "__HQ__"}:
        return HQ.resolve()
    p = Path(text)
    if not p.is_absolute():
        return (HQ / p).resolve()
    return p.resolve()


def _tool_roots() -> list[Path]:
    cfg = load_profile()
    roots = (cfg.get("tools") or {}).get("roots") or ["."]
    out: list[Path] = []
    for r in roots:
        p = resolve_profile_path(str(r))
        if p.exists():
            out.append(p)
    return out or [HQ.resolve()]


def _broad_read_roots() -> list[Path]:
    cfg = load_profile()
    tools = cfg.get("tools") or {}
    raw = tools.get("broadReadRoots") or []
    if not raw:
        raw = [str(Path.home()), str(Path.home() / "Desktop")]
    out: list[Path] = []
    for r in raw:
        try:
            p = resolve_profile_path(str(r)) if str(r).strip() in {".", "./", "__HQ__"} else Path(r).expanduser().resolve()
            if p.exists():
                out.append(p)
        except OSError:
            continue
    return out or _tool_roots()


def _read_policy() -> str:
    return (load_profile().get("tools") or {}).get("readPolicy") or "sandbox"


def _is_unrestricted_read() -> bool:
    return _read_policy() == "unrestricted"


def _drive_roots() -> list[Path]:
    """Existing drive letters (Windows) — used by unrestricted read."""
    out: list[Path] = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{letter}:\\")
        try:
            if root.exists():
                out.append(root.resolve())
        except OSError:
            continue
    return out


def _blocked_read_path(p: Path) -> bool:
    s = str(p).lower().replace("/", "\\")
    blocks = (
        "\\windows\\",
        "\\program files",
        "\\program files (x86)",
        "\\appdata\\local\\packages\\",
        "\\system volume information",
        "\\$recycle.bin",
    )
    if any(b in s for b in blocks):
        return True
    if not _is_unrestricted_read():
        if p.suffix.lower() in {".exe", ".dll", ".msi", ".cab", ".iso"}:
            return True
        try:
            if p.is_file() and p.stat().st_size > 8_000_000:
                return True
        except OSError:
            return True
    return False


def _read_roots() -> list[Path]:
    policy = _read_policy()
    if policy == "unrestricted":
        seen: set[str] = set()
        merged: list[Path] = []
        for p in _drive_roots() + _tool_roots() + _broad_read_roots():
            key = str(p)
            if key not in seen:
                seen.add(key)
                merged.append(p)
        return merged
    if policy == "broad":
        seen: set[str] = set()
        merged: list[Path] = []
        for p in _tool_roots() + _broad_read_roots():
            key = str(p)
            if key not in seen:
                seen.add(key)
                merged.append(p)
        return merged
    return _tool_roots()


def tool_roots_labeled() -> list[dict]:
    """Readable roots with labels from agent-profile index config."""
    cfg = load_profile()
    index_roots = {
        resolve_profile_path(str(r["path"])): r.get("label") or r.get("id")
        for r in (cfg.get("index") or {}).get("roots") or []
    }
    items: list[dict] = []
    if _is_unrestricted_read():
        for p in _drive_roots():
            items.append({"path": str(p), "label": f"{p.drive} 全盘"})
        return items
    for p in _read_roots():
        items.append({"path": str(p), "label": index_roots.get(p) or p.name})
    return items


def format_tool_roots_block() -> str:
    items = tool_roots_labeled()
    policy = _read_policy()
    if not items:
        return "## 可读沙箱\n- （未配置 tools.roots）"
    lines = [f"## 可读范围（readPolicy={policy}）"]
    if policy == "unrestricted":
        lines.append("- **unrestricted 模式**：可读本机所有盘符下文件（仅屏蔽 Windows/Program Files 等系统目录）")
    elif policy == "broad":
        lines.append("- **broad 模式**：用户目录 + Desktop + tools.roots（屏蔽 Windows/Program Files/大二进制）")
    else:
        lines.append("- **sandbox 模式**：仅限 tools.roots")
    for it in items[:12]:
        lines.append(f"- **{it['label']}** · `{it['path']}`")
    if len(items) > 12:
        lines.append(f"- …共 {len(items)} 个根")
    lines.append("- 路径不存在时会 search_index / glob；仍读不到就明确告知")
    return "\n".join(lines)


PATH_IN_TEXT_RE = re.compile(
    r"(?:[A-Za-z]:\\(?:[^\\/\s\"<>|]+\\)*[^\\/\s\"<>|]*)"
    r"|(?:/(?:[\w.\-]+/)*[\w.\-]+)"
)


def extract_paths_from_text(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for m in PATH_IN_TEXT_RE.finditer(text or ""):
        p = m.group(0).strip().rstrip(".,;:!?）)】\"'")
        if len(p) < 3 or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out[:6]


def format_context_paths_inject(context_paths: list[dict], *, max_chars: int = 8000) -> str:
    """Prefetch @file / @codebase picks for prompt injection."""
    if not context_paths:
        return ""
    lines = ["## @ 上下文（用户手动附加 · 必须优先参考）"]
    used = len(lines[0])
    for i, c in enumerate(context_paths, 1):
        path = (c.get("path") or c.get("name") or "").strip()
        if not path:
            continue
        kind = c.get("kind") or "file"
        label = c.get("label") or path
        if kind == "codebase" and c.get("snippet"):
            block = (
                f"\n### [{i}] ⌕codebase · `{label}`\n路径：`{path}`\n"
                f"```\n{str(c.get('snippet') or '')[:1500]}\n```"
            )
        elif kind == "git" and path == "git://status":
            try:
                r = subprocess.run(
                    ["git", "status", "-sb"],
                    cwd=str(HQ),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                stat = subprocess.run(
                    ["git", "diff", "--stat"],
                    cwd=str(HQ),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                body = (r.stdout or r.stderr or "").strip()[:800]
                diff_stat = (stat.stdout or "").strip()[:600]
                block = f"\n### [{i}] @git · 工作区状态\n```\n{body}\n```"
                if diff_stat:
                    block += f"\n```\n{diff_stat}\n```"
            except Exception as e:
                block = f"\n### [{i}] @git\n无法读取 git 状态：{e}"
        elif kind == "web":
            block = (
                f"\n### [{i}] @web\n"
                "用户希望结合网络检索回答；若可用请优先查证最新资料并注明来源。"
            )
        else:
            result = probe_path(path)
            if result.get("content"):
                block = f"\n### [{i}] @file · `{label}`\n```\n{result['content'][:2000]}\n```"
            elif result.get("items"):
                items = json.dumps(result.get("items") or [], ensure_ascii=False)[:1500]
                block = f"\n### [{i}] @dir · `{label}`\n```json\n{items}\n```"
            elif result.get("ok"):
                block = f"\n### [{i}] `{path}`\n```json\n{json.dumps(result, ensure_ascii=False)[:1500]}\n```"
            else:
                block = f"\n### [{i}] `{path}`（不可读）\n{result.get('error') or '路径无效'}"
        if used + len(block) > max_chars:
            break
        lines.append(block)
        used += len(block)
    return "\n".join(lines) if len(lines) > 1 else ""


def probe_path(path_str: str) -> dict:
    """Try list_dir (dir) or read_file (file) for orchestrator prefetch."""
    fp = _smart_resolve(path_str)
    if not fp:
        return {"ok": False, "path": path_str, "error": "不在可读沙箱内", "allowed_roots": tool_roots_labeled()}
    if fp.is_dir():
        return tool_list_dir(str(fp))
    if fp.is_file():
        return tool_read_file(str(fp), offset=1, limit=80)
    return {"ok": False, "path": str(fp), "error": "路径不存在"}


def _smart_resolve(path_str: str) -> Path | None:
    """Resolve path: direct → HQ-relative → each tool root → unique basename rglob."""
    fp = _resolve_allowed(path_str)
    if fp:
        return fp
    raw = (path_str or "").strip().strip('"').strip("'")
    if not raw or raw in (".", "./"):
        return _resolve_allowed(str(HQ))
    norm = raw.replace("/", "\\")
    # Try under each writable/readable project root first (most common mistake)
    for root in _tool_roots():
        candidate = (root / norm).resolve()
        if _blocked_read_path(candidate):
            continue
        ok_root = False
        for r in _read_roots():
            try:
                candidate.relative_to(r)
                ok_root = True
                break
            except ValueError:
                continue
        if ok_root and candidate.exists():
            return candidate
    # Single-segment basename: scripts/foo.py → rglob once
    parts = [p for p in norm.split("\\") if p]
    if parts:
        tail = parts[-1]
        if "." in tail and len(parts) <= 3:
            found: list[Path] = []
            for root in _tool_roots():
                try:
                    for hit in root.rglob(tail):
                        if _blocked_read_path(hit):
                            continue
                        for r in _read_roots():
                            try:
                                hit.relative_to(r)
                                found.append(hit.resolve())
                                break
                            except ValueError:
                                continue
                        if len(found) >= 6:
                            break
                except OSError:
                    continue
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                # Let caller surface ambiguity
                return None
    return None


def _path_failure_hint(path_str: str) -> dict:
    """Actionable hints when read/list/grep path fails — reduce agent retry loops."""
    roots = tool_roots_labeled()[:8]
    hints = [
        "用 list_dir 列目录确认路径；或用 glob 按文件名搜索",
        "相对路径请基于项目根，例如 scripts/juno_agent.py",
        "可用 search_index 语义检索代替盲目 read",
    ]
    raw = (path_str or "").strip()
    if raw and not Path(raw.replace("/", "\\")).is_absolute():
        for r in roots[:3]:
            hints.append(f"尝试绝对路径：{r['path']}\\{raw.replace('/', chr(92))}")
    return {
        "hint": " · ".join(hints[:3]),
        "allowed_roots": roots,
        "hq": str(HQ),
    }


def _resolve_allowed(path_str: str) -> Path | None:
    raw = (path_str or "").strip().replace("/", "\\")
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = (HQ / raw).resolve()
    else:
        p = p.resolve()
    if _blocked_read_path(p):
        return None
    for root in _read_roots():
        try:
            p.relative_to(root)
            return p
        except ValueError:
            continue
    return None


def tool_read_file(path: str, *, offset: int = 1, limit: int = 120) -> dict:
    fp = _smart_resolve(path)
    if not fp or not fp.is_file():
        out = {"ok": False, "error": f"文件不可访问或不存在: {path}"}
        out.update(_path_failure_hint(path))
        return out
    try:
        lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return {"ok": False, "error": str(e)}
    start = max(0, offset - 1)
    end = min(len(lines), start + limit)
    snippet = "\n".join(f"{i+1}|{lines[i]}" for i in range(start, end))
    return {"ok": True, "path": str(fp), "lines": f"{start+1}-{end}", "content": snippet}


def tool_list_dir(path: str = ".", *, max_entries: int = 80) -> dict:
    fp = _smart_resolve(path or ".") or _smart_resolve(str(HQ))
    if not fp or not fp.is_dir():
        out = {"ok": False, "error": f"目录不可访问: {path}"}
        out.update(_path_failure_hint(path))
        return out
    entries = []
    for item in sorted(fp.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:max_entries]:
        kind = "dir" if item.is_dir() else "file"
        entries.append({"name": item.name, "type": kind})
    return {"ok": True, "path": str(fp), "entries": entries}


def tool_grep(pattern: str, path: str = ".", *, max_hits: int = 30, context: int = 0) -> dict:
    fp = _smart_resolve(path or ".") or _smart_resolve(str(HQ))
    if not fp:
        out = {"ok": False, "error": f"路径不可访问: {path}"}
        out.update(_path_failure_hint(path))
        return out
    import shutil
    import subprocess

    rg = shutil.which("rg")
    if rg:
        cmd = [rg, "-n", "--no-heading", "--color=never", "-m", str(max_hits)]
        if context:
            cmd.extend(["-C", str(context)])
        cmd.extend(["-e", pattern, str(fp)])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace")
            hits = []
            for line in (proc.stdout or "").splitlines():
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    hits.append({"path": parts[0], "line": int(parts[1]) if parts[1].isdigit() else 0, "text": parts[2][:240]})
                elif line.strip():
                    hits.append({"path": str(fp), "line": 0, "text": line[:240]})
                if len(hits) >= max_hits:
                    break
            if hits or proc.returncode in (0, 1):
                return {"ok": True, "hits": hits, "truncated": len(hits) >= max_hits, "engine": "rg"}
        except (subprocess.TimeoutExpired, OSError):
            pass
    try:
        rx = re.compile(pattern, re.I)
    except re.error as e:
        return {"ok": False, "error": f"无效正则: {e}"}
    hits = []
    files = [fp] if fp.is_file() else list(fp.rglob("*"))
    for f in files:
        if not f.is_file() or f.stat().st_size > 512_000:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            if rx.search(line):
                snippet = line[:240]
                if context:
                    lo = max(0, i - 1 - context)
                    hi = min(len(lines), i + context)
                    snippet = "\n".join(f"{j+1}|{lines[j]}" for j in range(lo, hi))
                hits.append({"path": str(f), "line": i, "text": snippet})
                if len(hits) >= max_hits:
                    return {"ok": True, "hits": hits, "truncated": True, "engine": "python"}
    return {"ok": True, "hits": hits, "truncated": False, "engine": "python"}


def tool_glob(pattern: str, path: str = ".", *, max_matches: int = 40) -> dict:
    fp = _resolve_allowed(path) or _resolve_allowed(".")
    if not fp or not fp.is_dir():
        return {"ok": False, "error": f"目录不可访问: {path}"}
    matches = []
    try:
        for item in fp.glob(pattern):
            matches.append(str(item))
            if len(matches) >= max_matches:
                break
    except OSError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "path": str(fp), "pattern": pattern, "matches": matches}


_SESSION_ID: str | None = None
EDIT_ROOT = HQ / "memory" / "session-edits"


def set_session_context(session_id: str | None) -> None:
    global _SESSION_ID
    _SESSION_ID = (session_id or "").strip() or None


def _backup_path(fp: Path) -> Path | None:
    if not _SESSION_ID:
        return None
    dest = EDIT_ROOT / _SESSION_ID / fp.name
    n = 1
    while dest.exists():
        dest = EDIT_ROOT / _SESSION_ID / f"{fp.stem}_{n}{fp.suffix}"
        n += 1
    return dest


def _record_edit(fp: Path, backup: str | None, *, hunks: list[dict] | None = None, diff: str = "") -> None:
    if not _SESSION_ID:
        return
    meta = EDIT_ROOT / _SESSION_ID / "manifest.json"
    items = []
    if meta.exists():
        try:
            items = json.loads(meta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            items = []
    entry = {
        "path": str(fp),
        "backup": backup,
        "time": datetime.now().isoformat(timespec="seconds"),
        "hunks": hunks or [],
        "diff": diff,
    }
    # merge hunks if same path
    for i, it in enumerate(items):
        if it.get("path") == str(fp):
            prev = it.get("hunks") or []
            entry["hunks"] = prev + (hunks or [])
            entry["backup"] = entry["backup"] or it.get("backup")
            items[i] = entry
            meta.write_text(json.dumps(items[-80:], ensure_ascii=False, indent=2), encoding="utf-8")
            return
    items.append(entry)
    meta.write_text(json.dumps(items[-80:], ensure_ascii=False, indent=2), encoding="utf-8")


def _backup_file(fp: Path) -> str | None:
    if not fp.is_file():
        return None
    dest = _backup_path(fp)
    if not dest:
        return None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(fp.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        return str(dest)
    except OSError:
        return None


def apply_hunk_edit(session_id: str, path: str, hunk_id: str, action: str) -> dict:
    import juno_diff
    meta = EDIT_ROOT / session_id / "manifest.json"
    if not meta.exists():
        return {"ok": False, "error": "无编辑记录"}
    try:
        items = json.loads(meta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "error": "manifest 损坏"}
    for it in items:
        if it.get("path") != path:
            continue
        for h in it.get("hunks") or []:
            if str(h.get("id")) != str(hunk_id):
                continue
            r = juno_diff.apply_hunk_action(path, h, action)
            meta.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            return r
        return {"ok": False, "error": f"未找到 hunk {hunk_id}"}
    return {"ok": False, "error": "未找到文件编辑记录"}


def list_session_edits(session_id: str) -> list[dict]:
    meta = EDIT_ROOT / session_id / "manifest.json"
    if not meta.exists():
        return []
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def revert_session_edits(session_id: str, *, paths: list[str] | None = None) -> dict:
    items = list_session_edits(session_id)
    if not items:
        return {"ok": False, "error": "无备份可还原"}
    reverted = []
    for it in reversed(items):
        target = it.get("path") or ""
        if paths and target not in paths:
            continue
        backup = Path(it.get("backup") or "")
        if not backup.exists() or not target:
            continue
        try:
            Path(target).write_text(backup.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            reverted.append(target)
        except OSError:
            continue
    return {"ok": True, "reverted": reverted}


def get_diff_preview(session_id: str, path: str) -> dict:
    """Original (backup) vs modified (disk) for Monaco diff editor."""
    target = path.strip()
    for it in list_session_edits(session_id):
        if it.get("path") != target:
            continue
        backup = Path(it.get("backup") or "")
        fp = Path(target)
        original = ""
        modified = ""
        if backup.is_file():
            original = backup.read_text(encoding="utf-8", errors="replace")
        if fp.is_file():
            modified = fp.read_text(encoding="utf-8", errors="replace")
        ext = fp.suffix.lower().lstrip(".")
        lang_map = {"py": "python", "ts": "typescript", "tsx": "typescript", "js": "javascript", "jsx": "javascript", "json": "json", "html": "html", "css": "css", "md": "markdown"}
        return {
            "ok": True,
            "path": target,
            "original": original,
            "modified": modified,
            "language": lang_map.get(ext, "plaintext"),
            "hunks": it.get("hunks") or [],
        }
    if Path(target).is_file():
        text = Path(target).read_text(encoding="utf-8", errors="replace")
        ext = Path(target).suffix.lower().lstrip(".")
        lang_map = {"py": "python", "ts": "typescript", "tsx": "typescript", "js": "javascript", "jsx": "javascript", "json": "json", "html": "html", "css": "css", "md": "markdown"}
        return {"ok": True, "path": target, "original": text, "modified": text, "language": lang_map.get(ext, "plaintext"), "hunks": []}
    return {"ok": False, "error": "文件不可读或无编辑记录"}


def tool_inline_edit(path: str, instruction: str, selection: str = "") -> dict:
    """Cmd+K style one-shot edit: LLM produces str_replace pair."""
    import juno_brain

    instruction = (instruction or "").strip()
    if not instruction:
        return {"ok": False, "error": "instruction required"}
    if not (path or "").strip():
        return {"ok": False, "error": "path required"}
    fp = _resolve_allowed(path)
    if not fp or not fp.is_file():
        return {"ok": False, "error": f"文件不可访问: {path}"}
    try:
        text = fp.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "error": str(e)}
    focus = (selection or "").strip() or text
    if len(focus) > 12000:
        focus = focus[:12000] + "\n…"
    messages = [
        {
            "role": "system",
            "content": (
                "你是 inline edit 助手。根据用户指令修改代码。"
                '只输出一个 JSON 对象，不要 markdown：'
                '{"old_string":"要在文件中唯一匹配的原文片段","new_string":"修改后的片段"}'
                "old_string 必须精确来自文件且唯一出现一次。"
            ),
        },
        {
            "role": "user",
            "content": f"文件：{path}\n\n```\n{focus}\n```\n\n指令：{instruction}",
        },
    ]
    reply, _ = juno_brain.chat_complete(messages, temperature=0.2)
    raw = (reply or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": "LLM 未返回有效 JSON", "raw": raw[:500]}
    old_s = data.get("old_string") or ""
    new_s = data.get("new_string")
    if new_s is None:
        return {"ok": False, "error": "缺少 new_string"}
    if not old_s:
        return {"ok": False, "error": "缺少 old_string"}
    return tool_str_replace(path, old_s, new_s)


def clear_session_edits(session_id: str) -> dict:
    folder = EDIT_ROOT / session_id
    if not folder.exists():
        return {"ok": True, "cleared": 0}
    count = sum(1 for _ in folder.glob("*"))
    import shutil
    try:
        shutil.rmtree(folder)
        return {"ok": True, "cleared": count}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def tool_str_replace(path: str, old_string: str, new_string: str) -> dict:
    fp = _resolve_allowed(path)
    if not fp or not fp.is_file():
        return {"ok": False, "error": f"文件不可访问或不存在: {path}"}
    try:
        text = fp.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "error": str(e)}
    count = text.count(old_string)
    if count == 0:
        return {"ok": False, "error": "old_string 未在文件中找到"}
    if count > 1:
        return {"ok": False, "error": f"old_string 出现 {count} 次，须唯一才能替换"}
    backup = _backup_file(fp)
    new_text = text.replace(old_string, new_string, 1)
    try:
        fp.write_text(new_text, encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": str(e)}
    import juno_diff
    hunks = juno_diff.build_hunks(old_string, new_string)
    diff_lines = []
    for h in hunks:
        diff_lines.append(h.get("preview_old") or "")
        diff_lines.append(h.get("preview_new") or "")
    diff = "\n".join(diff_lines)
    _record_edit(fp, backup, hunks=hunks, diff=diff)
    try:
        import juno_agent_trace
        import juno_brain
        st = juno_brain.chat_status()
        model = st.get("model") if isinstance(st, dict) else None
        ranges = juno_agent_trace.compute_range_positions(old_string, new_string, new_text)
        trace = juno_agent_trace.create_trace(
            fp,
            session_id=_SESSION_ID,
            model=model,
            range_positions=ranges,
        )
        juno_agent_trace.append_trace(trace)
    except Exception:
        pass
    return {
        "ok": True,
        "path": str(fp),
        "replaced": True,
        "diff": diff,
        "hunks": hunks,
        "backup": backup,
    }


def tool_apply_patch(path: str, patch: str) -> dict:
    """Write patched/full content to a project file (within tool roots)."""
    fp = _resolve_allowed(path)
    if not fp:
        return {"ok": False, "error": f"路径不可访问: {path}"}
    content = patch or ""
    if not content.strip():
        return {"ok": False, "error": "patch 内容为空"}
    try:
        fp.parent.mkdir(parents=True, exist_ok=True)
        backup = _backup_file(fp) if fp.exists() else None
        fp.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(fp), "patched": True, "bytes": len(content.encode("utf-8")), "backup": backup}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def tool_delete_file(path: str, *, confirm: bool = False) -> dict:
    if not confirm:
        return {"ok": False, "error": "delete_file 需要 confirm=true"}
    fp = _resolve_write(path) or _resolve_allowed(path)
    if not fp or not fp.is_file():
        return {"ok": False, "error": f"文件不可删除: {path}"}
    # only memory/knowledge or explicit small files
    wr = _write_roots()
    allowed = False
    for root in wr:
        try:
            fp.resolve().relative_to(root)
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        return {"ok": False, "error": "仅允许删除 memory/ 或 knowledge/ 内文件"}
    try:
        fp.unlink()
        return {"ok": True, "path": str(fp), "deleted": True}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def tool_web_fetch(url: str, *, max_chars: int = 12000) -> dict:
    import urllib.error
    import urllib.request

    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        return {"ok": False, "error": "仅支持 http(s) URL"}

    # GitHub repo → try README via API (lighter than full HTML)
    gh = re.match(r"https?://github\.com/([^/]+)/([^/?#]+)", u)
    if gh and "/search" not in u and "/topics" not in u:
        owner, repo = gh.group(1), gh.group(2).removesuffix(".git")
        api = f"https://api.github.com/repos/{owner}/{repo}/readme"
        try:
            req = urllib.request.Request(
                api,
                headers={"User-Agent": "Juno-Agent/1.1", "Accept": "application/vnd.github.raw"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            text = re.sub(r"\s+", " ", text).strip()
            return {
                "ok": True,
                "url": u,
                "content_type": "text/markdown",
                "content": text[:max_chars],
                "truncated": len(text) > max_chars,
                "source": "github-readme",
            }
        except Exception:
            pass  # fall through to HTML fetch

    req = urllib.request.Request(
        u,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read(512_000)
            ctype = resp.headers.get("Content-Type", "")
    except urllib.error.URLError as e:
        return {"ok": False, "error": str(e.reason if hasattr(e, "reason") else e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return {"ok": False, "error": "响应非 UTF-8 文本，已跳过"}
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return {
        "ok": True,
        "url": u,
        "content_type": ctype,
        "content": text[:max_chars],
        "truncated": len(text) > max_chars,
    }


TODO_FILE = HQ / "memory" / "agent-todos.json"


def _load_todos() -> list[dict]:
    if not TODO_FILE.exists():
        return []
    try:
        data = json.loads(TODO_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _save_todos(items: list[dict]) -> None:
    TODO_FILE.parent.mkdir(parents=True, exist_ok=True)
    TODO_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def tool_todo(action: str, *, content: str = "", todo_id: str = "") -> dict:
    action = (action or "list").strip().lower()
    items = _load_todos()
    if action == "list":
        return {"ok": True, "todos": items}
    if action == "clear":
        _save_todos([])
        return {"ok": True, "todos": []}
    if action == "add":
        if not content.strip():
            return {"ok": False, "error": "add 需要 content"}
        tid = todo_id or str(len(items) + 1)
        items.append({"id": tid, "content": content.strip(), "done": False})
        _save_todos(items[-30:])
        return {"ok": True, "todos": items}
    if action == "done":
        if not todo_id:
            return {"ok": False, "error": "done 需要 todo_id"}
        for it in items:
            if str(it.get("id")) == str(todo_id):
                it["done"] = True
                _save_todos(items)
                return {"ok": True, "todos": items}
        return {"ok": False, "error": f"未找到 todo_id={todo_id}"}
    return {"ok": False, "error": f"未知 action: {action}（list/add/done/clear）"}


def tool_search_index(query: str, *, top_k: int = 6) -> dict:
    import juno_index

    hits = juno_index.search(query, top_k=top_k)
    return {"ok": True, "hits": hits}


_CD_CMD_RE = re.compile(
    r'^cd(\s+/d)?\s+("(?P<q1>[^"]+)"|\'(?P<q2>[^\']+)\'|(?P<plain>\S+))\s*$',
    re.I,
)


def _matches_allow(s: str, pattern: str) -> bool:
    if s == pattern:
        return True
    if pattern.endswith(" "):
        return s.startswith(pattern) or s == pattern.rstrip()
    return s.startswith(pattern + " ")


def _segment_shell_allowed(seg: str, allow: list[str]) -> bool:
    s = (seg or "").strip()
    if not s:
        return True
    if any(_matches_allow(s, a) for a in allow):
        return True
    m = _CD_CMD_RE.match(s)
    if m:
        path = m.group("q1") or m.group("q2") or m.group("plain") or ""
        return _resolve_allowed(path) is not None
    return False


def _shell_allowed(cmd: str) -> bool:
    cfg = load_profile()
    allow = (cfg.get("tools") or {}).get("shellAllowlist") or []
    c = (cmd or "").strip()
    if not c:
        return False
    segments = re.split(r"\s*&&\s*|\s*;\s*", c)
    if len(segments) == 1:
        return _segment_shell_allowed(c, allow)
    return all(_segment_shell_allowed(seg, allow) for seg in segments)


def _write_roots() -> list[Path]:
    cfg = load_profile()
    raw = (cfg.get("tools") or {}).get("writeRoots") or ["memory", "knowledge"]
    out: list[Path] = []
    for r in raw:
        p = resolve_profile_path(str(r))
        p.mkdir(parents=True, exist_ok=True)
        out.append(p)
    return out or [(HQ / "memory").resolve(), (HQ / "knowledge").resolve()]


def _resolve_write(path_str: str) -> Path | None:
    raw = (path_str or "").strip().replace("/", "\\")
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = (HQ / raw).resolve()
    else:
        p = p.resolve()
    for root in _write_roots():
        try:
            p.relative_to(root)
            return p
        except ValueError:
            continue
    return None


def tool_write_file(path: str, content: str, *, append: bool = False) -> dict:
    fp = _resolve_write(path)
    if not fp:
        return {"ok": False, "error": f"写入路径不在沙箱内（仅 memory/、knowledge/）: {path}"}
    try:
        fp.parent.mkdir(parents=True, exist_ok=True)
        if append and fp.exists():
            with fp.open("a", encoding="utf-8") as f:
                f.write(content)
        else:
            fp.write_text(content or "", encoding="utf-8")
        nbytes = len((content or "").encode("utf-8"))
        return {"ok": True, "path": str(fp), "bytes": nbytes, "append": bool(append)}
    except OSError as e:
        return {"ok": False, "error": str(e)}


_BG_SHELL_RE = re.compile(r"^\s*(start(\s+/[a-z]+)?\s|Start-Process\b)", re.I)
_LONG_RUN_RE = re.compile(
    r"(npm\s+run|pnpm\s+run|yarn\s+run|npx\s+|electron\b|vite\b|next\s+dev|nodemon\b|webpack\s+serve|python\s+.*serve)",
    re.I,
)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_BG_JOBS: dict[str, dict] = {}


def _is_background_shell(cmd: str) -> bool:
    return bool(_BG_SHELL_RE.match(cmd or ""))


def _unwrap_windows_start(command: str) -> str:
    cmd = (command or "").strip()
    if not _is_background_shell(cmd):
        return cmd
    for pat in (
        r'^\s*start(?:\s+/[a-z]+)*\s+cmd(?:\.exe)?\s+/k\s+"(.+)"\s*$',
        r"^\s*start(?:\s+/[a-z]+)*\s+cmd(?:\.exe)?\s+/k\s+'(.+)'\s*$",
        r'^\s*start(?:\s+/[a-z]+)*\s+cmd(?:\.exe)?\s+/c\s+"(.+)"\s*$',
    ):
        m = re.match(pat, cmd, re.I | re.S)
        if m:
            return m.group(1).strip()
    return cmd


def _should_integrated_background(command: str) -> bool:
    cmd = _unwrap_windows_start(command)
    return bool(_is_background_shell(command) or _LONG_RUN_RE.search(cmd))


def _spawn_integrated_job(command: str, cwd: Path) -> dict:
    job_id = uuid.uuid4().hex[:10]
    lines: list[str] = []

    kw: dict = {
        "shell": True,
        "cwd": str(cwd),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    if os.name == "nt":
        kw["creationflags"] = CREATE_NO_WINDOW
    proc = subprocess.Popen(command, **kw)

    def _reader() -> None:
        try:
            if proc.stdout:
                for chunk in iter(proc.stdout.readline, ""):
                    lines.append(chunk)
                    if len(lines) > 3000:
                        lines.pop(0)
        finally:
            code = proc.wait()
            job = _BG_JOBS.get(job_id)
            if job:
                job["done"] = True
                job["code"] = code

    _BG_JOBS[job_id] = {
        "proc": proc,
        "lines": lines,
        "command": command,
        "cwd": str(cwd),
        "done": False,
        "code": None,
        "pid": proc.pid,
    }
    threading.Thread(target=_reader, name=f"juno-shell-{job_id}", daemon=True).start()
    return {
        "ok": True,
        "background": True,
        "integrated": True,
        "job_id": job_id,
        "pid": proc.pid,
        "command": command,
        "cwd": str(cwd),
        "output": f"已在 Juno 内置终端启动 (job {job_id})",
        "stdout": "",
    }


def get_shell_job(job_id: str, *, offset: int = 0) -> dict:
    job = _BG_JOBS.get((job_id or "").strip())
    if not job:
        return {"ok": False, "error": "job not found"}
    lines: list[str] = job["lines"]
    off = max(0, int(offset))
    chunk = "".join(lines[off:])
    return {
        "ok": True,
        "job_id": job_id,
        "command": job.get("command"),
        "output": chunk,
        "next_offset": len(lines),
        "done": bool(job.get("done")),
        "code": job.get("code"),
        "pid": job.get("pid"),
    }


def tool_run_shell(command: str, *, cwd: str | None = None) -> dict:
    if not _shell_allowed(command):
        allow = (load_profile().get("tools") or {}).get("shellAllowlist") or []
        preview = ", ".join(str(a).strip() for a in allow[:12])
        return {
            "ok": False,
            "error": "命令不在白名单，已拒绝",
            "hint": f"允许前缀示例：{preview}… 长驻 dev 直接 run_shell + cwd，输出在 Juno 内置终端",
            "command": command,
        }
    work = _smart_resolve(cwd or str(HQ)) or HQ
    command = _unwrap_windows_start(command)
    try:
        if _should_integrated_background(command):
            return _spawn_integrated_job(command, work)
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(work),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "output": out[:8000],
            "stdout": out[:8000],
            "command": command,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "命令超时 (60s)。长驻 dev 请用 run_shell + cwd 直接启动（npm run dev / electron），勿用 start cmd",
            "command": command,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "command": command}


TOOL_DEFS = [
    {"name": "read_file", "desc": "读取沙箱内文本文件片段", "args": {"path": "str", "offset": "int?", "limit": "int?"}},
    {"name": "list_dir", "desc": "列出目录", "args": {"path": "str?"}},
    {"name": "glob", "desc": "按 glob 模式找文件", "args": {"pattern": "str", "path": "str?"}},
    {"name": "grep", "desc": "在路径下正则搜索", "args": {"pattern": "str", "path": "str?"}},
    {"name": "search_index", "desc": "混合语义检索已索引仓库", "args": {"query": "str"}},
    {"name": "web_search", "desc": "网络搜索（调研）", "args": {"query": "str"}},
    {"name": "web_fetch", "desc": "抓取网页文本", "args": {"url": "str"}},
    {"name": "read_lints", "desc": "读取文件 lint/语法诊断", "args": {"path": "str?", "paths": "list?"}},
    {"name": "str_replace", "desc": "替换项目文件唯一字符串", "args": {"path": "str", "old_string": "str", "new_string": "str"}},
    {"name": "apply_patch", "desc": "应用 patch 到文件", "args": {"path": "str", "patch": "str"}},
    {"name": "write_file", "desc": "写入 memory/knowledge 沙箱", "args": {"path": "str", "content": "str", "append": "bool?"}},
    {"name": "delete_file", "desc": "删除沙箱内文件", "args": {"path": "str", "confirm": "bool?"}},
    {"name": "git", "desc": "git status/diff/log/commit", "args": {"action": "str", "message": "str?", "paths": "list?"}},
    {"name": "todo", "desc": "任务清单 list/add/done/clear", "args": {"action": "str", "content": "str?", "todo_id": "str?"}},
    {"name": "run_shell", "desc": "运行白名单 shell 命令", "args": {"command": "str", "cwd": "str?"}},
    {"name": "task", "desc": "启动子代理 explore/shell（Cursor Task 同款）", "args": {"action": "str", "kind": "str?", "prompt": "str?", "tasks": "list?"}},
    {"name": "mcp_call", "desc": "调用入站 MCP 工具", "args": {"server": "str", "tool": "str", "arguments": "str?"}},
]


def tool_schemas() -> list[dict]:
    """OpenAI-compatible tool schemas for native function calling."""
    schemas = []
    for t in TOOL_DEFS:
        props = {}
        required = []
        for k, v in (t.get("args") or {}).items():
            optional = str(v).endswith("?")
            typ = "string"
            if "list" in str(v):
                typ = "array"
            elif "bool" in str(v):
                typ = "boolean"
            elif "int" in str(v):
                typ = "integer"
            props[k] = {"type": typ}
            if not optional:
                required.append(k)
        schemas.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["desc"],
                "parameters": {"type": "object", "properties": props, "required": required},
            },
        })
    return schemas


SKIP_TREE_NAMES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    ".nuxt",
    ".output",
    ".next",
    "coverage",
}


def list_dir_tree(path_str: str = "", *, depth: int = 2, max_nodes: int = 400) -> dict:
    """Shallow directory tree for file explorer UI."""
    depth = max(1, min(int(depth), 4))
    if not (path_str or "").strip():
        children = []
        for r in tool_roots_labeled():
            p = Path(r["path"])
            if p.exists():
                children.append({"name": r["label"], "path": str(p), "type": "dir"})
        return {"ok": True, "path": "", "children": children[:20]}

    fp = _resolve_allowed(path_str)
    if not fp:
        return {"ok": False, "path": path_str, "error": "不在可读沙箱内"}
    if not fp.is_dir():
        return {"ok": False, "path": str(fp), "error": "不是目录"}

    nodes = 0

    def walk(d: Path, dleft: int) -> list[dict]:
        nonlocal nodes
        out: list[dict] = []
        try:
            entries = sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except OSError:
            return out
        for ent in entries:
            if nodes >= max_nodes:
                break
            if ent.name in SKIP_TREE_NAMES or ent.name.startswith("."):
                continue
            nodes += 1
            item: dict = {
                "name": ent.name,
                "path": str(ent),
                "type": "dir" if ent.is_dir() else "file",
            }
            if ent.is_dir() and dleft > 1:
                item["children"] = walk(ent, dleft - 1)
            out.append(item)
        return out

    return {"ok": True, "path": str(fp), "children": walk(fp, depth)}


def list_mention_sources(*, kind: str = "files", q: str = "", limit: int = 50) -> list[dict]:
    """Items for extended @mention picker (rules, docs, folders, git, web)."""
    q_lower = (q or "").lower()
    items: list[dict] = []
    seen: set[str] = set()
    kind = (kind or "files").lower()

    if kind in ("rules", "all"):
        for rules_dir in [HQ / ".cursor" / "rules"]:
            if not rules_dir.exists():
                continue
            for fp in sorted(rules_dir.glob("*.mdc")):
                if q_lower and q_lower not in fp.stem.lower():
                    continue
                p = str(fp)
                if p in seen:
                    continue
                seen.add(p)
                items.append(
                    {
                        "path": p,
                        "label": fp.stem,
                        "name": fp.stem,
                        "kind": "rules",
                        "snippet": "Cursor rule",
                    }
                )
        for root in _read_roots():
            rd = root / ".cursor" / "rules"
            if not rd.exists():
                continue
            for fp in sorted(rd.glob("*.mdc")):
                if q_lower and q_lower not in fp.stem.lower():
                    continue
                p = str(fp)
                if p in seen:
                    continue
                seen.add(p)
                items.append(
                    {
                        "path": p,
                        "label": fp.stem,
                        "name": fp.stem,
                        "kind": "rules",
                        "snippet": f"规则 · {root.name}",
                    }
                )

    if kind in ("docs", "all"):
        doc_names = {"SOUL.md", "USER.md", "MEMORY.md", "AGENTS.md", "TOOLS.md"}
        for base in (HQ / "knowledge", HQ):
            if not base.exists():
                continue
            for fp in sorted(base.glob("*.md")):
                if base == HQ and fp.name not in doc_names:
                    continue
                if q_lower and q_lower not in fp.name.lower() and q_lower not in fp.stem.lower():
                    continue
                p = str(fp)
                if p in seen:
                    continue
                seen.add(p)
                items.append(
                    {
                        "path": p,
                        "label": fp.name,
                        "name": fp.stem,
                        "kind": "docs",
                        "snippet": "知识库文档",
                    }
                )

    if kind in ("folder", "folders", "all"):
        for r in tool_roots_labeled():
            p = Path(r["path"])
            if not p.is_dir():
                continue
            try:
                for ent in sorted(p.iterdir(), key=lambda x: x.name.lower()):
                    if not ent.is_dir() or ent.name in SKIP_TREE_NAMES or ent.name.startswith("."):
                        continue
                    if q_lower and q_lower not in ent.name.lower():
                        continue
                    ep = str(ent)
                    if ep in seen:
                        continue
                    seen.add(ep)
                    items.append(
                        {
                            "path": ep,
                            "label": ent.name,
                            "name": ent.name,
                            "kind": "folder",
                            "snippet": r["label"],
                        }
                    )
            except OSError:
                pass

    if kind in ("git", "all") and (
        not q_lower or "git".startswith(q_lower) or q_lower in ("git", "status", "st")
    ):
        items.append(
            {
                "path": "git://status",
                "label": "Git 状态",
                "name": "git-status",
                "kind": "git",
                "snippet": "git status -sb · diff --stat",
            }
        )

    if kind in ("web", "all") and (not q_lower or "web".startswith(q_lower) or q_lower == "web"):
        items.append(
            {
                "path": "web://search",
                "label": "Web 搜索",
                "name": "web",
                "kind": "web",
                "snippet": "结合网络检索回答",
            }
        )

    if kind in ("files", "all"):
        for it in list_browsable_files(q=q, limit=limit):
            p = it["path"]
            if p in seen:
                continue
            seen.add(p)
            items.append({**it, "kind": "file"})

    return items[:limit]


def list_browsable_files(*, q: str = "", limit: int = 80) -> list[dict]:
    """Flat file list for @ mention picker — index-first when query present."""
    items: list[dict] = []
    q_lower = (q or "").lower()
    seen: set[str] = set()

    if q_lower:
        import juno_index
        for hit in juno_index.search(q, top_k=limit):
            p = hit.get("path") or ""
            if not p or p in seen:
                continue
            fp = Path(p)
            if not fp.is_file():
                continue
            seen.add(p)
            items.append({"path": p, "label": fp.name, "name": fp.name})
        if items:
            return items[:limit]

    max_scan = 3000
    scanned = 0
    for root in _read_roots():
        try:
            for fp in root.rglob("*"):
                scanned += 1
                if scanned > max_scan:
                    break
                if not fp.is_file() or fp.stat().st_size > 2_000_000:
                    continue
                rel = str(fp.relative_to(root)).replace("\\", "/")
                label = f"{root.name}/{rel}"
                pstr = str(fp)
                if pstr in seen:
                    continue
                if q_lower and q_lower not in label.lower() and q_lower not in fp.name.lower():
                    continue
                seen.add(pstr)
                items.append({"path": pstr, "label": label, "name": fp.name})
                if len(items) >= limit:
                    return items
        except OSError:
            continue
    return sorted(items, key=lambda x: x["label"].lower())[:limit]


def run_tool(name: str, args: dict | None = None) -> dict:
    args = args or {}
    if _PLAN_MODE and name in PLAN_BLOCKED:
        return {"ok": False, "error": f"Plan 模式：禁止执行 {name}，请先输出方案"}
    if _READONLY and name in WRITE_TOOLS:
        return {"ok": False, "error": f"Ask 只读模式：禁止 {name}"}
    if name == "read_file":
        return tool_read_file(args.get("path", ""), offset=int(args.get("offset") or 1), limit=int(args.get("limit") or 120))
    if name == "list_dir":
        return tool_list_dir(args.get("path") or ".")
    if name == "grep":
        return tool_grep(args.get("pattern", ""), args.get("path") or ".")
    if name == "glob":
        return tool_glob(args.get("pattern", ""), args.get("path") or ".")
    if name == "search_index":
        return tool_search_index(args.get("query", ""))
    if name == "web_search":
        import juno_web
        return juno_web.web_search(args.get("query", ""))
    if name == "read_lints":
        import juno_lints
        paths = args.get("paths")
        if isinstance(paths, str):
            paths = [paths]
        return juno_lints.read_lints(paths=paths, path=args.get("path") or "")
    if name == "git":
        import juno_git
        return juno_git.git_workflow(
            args.get("action") or "status",
            message=args.get("message") or "",
            paths=args.get("paths"),
            cwd=args.get("cwd") or "",
        )
    if name == "write_file":
        return tool_write_file(
            args.get("path", ""),
            args.get("content") or "",
            append=bool(args.get("append")),
        )
    if name == "str_replace":
        return tool_str_replace(
            args.get("path", ""),
            args.get("old_string") or "",
            args.get("new_string") or "",
        )
    if name == "apply_patch":
        return tool_apply_patch(args.get("path", ""), args.get("patch") or "")
    if name == "delete_file":
        return tool_delete_file(args.get("path", ""), confirm=bool(args.get("confirm")))
    if name == "web_fetch":
        return tool_web_fetch(args.get("url", ""))
    if name == "todo":
        return tool_todo(
            args.get("action") or "list",
            content=args.get("content") or "",
            todo_id=args.get("todo_id") or "",
        )
    if name == "run_shell":
        return tool_run_shell(args.get("command", ""), cwd=args.get("cwd"))
    if name == "task":
        if _PLAN_MODE:
            kind = (args.get("kind") or "explore").lower()
            if (args.get("action") or "run").lower() == "parallel" or kind == "shell":
                return {"ok": False, "error": "Plan 模式：仅允许 explore 只读子代理"}
        import juno_subagent
        tasks = args.get("tasks")
        if isinstance(tasks, str):
            try:
                tasks = json.loads(tasks)
            except json.JSONDecodeError:
                tasks = None
        return juno_subagent.tool_task(
            args.get("action") or "run",
            kind=args.get("kind") or "explore",
            prompt=args.get("prompt") or "",
            tasks=tasks,
        )
    if name == "mcp_call":
        import juno_mcp_client
        arguments = args.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        return juno_mcp_client.tool_mcp_call(args.get("server", ""), args.get("tool", ""), arguments)
    return {"ok": False, "error": f"未知工具: {name}"}
