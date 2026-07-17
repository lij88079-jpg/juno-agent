#!/usr/bin/env python3
"""Sandboxed tools for Juno Agent mode (read / search / limited shell)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
PROFILE = HQ / "config" / "agent-profile.json"
PROFILE_LOCAL = HQ / "config" / "agent-profile.local.json"
_READONLY = False
_PLAN_MODE = False
# Paths the user explicitly @ / dragged this session (read + write under that root).
_SESSION_TRUSTED_ROOTS: list[Path] = []
WRITE_TOOLS = {"write_file", "str_replace", "apply_patch", "delete_file", "git", "run_shell", "todo"}
PLAN_BLOCKED = {"write_file", "str_replace", "apply_patch", "delete_file", "git", "run_shell"}
# Cursor-like open shell: allow by default; only block obvious destructive patterns.
_SHELL_DENY_RE = re.compile(
    r"(?is)"
    r"("
    r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)*[\"']?/|"
    r"\bformat\s+[a-z]:"
    r"|"
    r"\b(del|erase)\s+/[sfq].*[\\/](windows|system32)"
    r"|"
    r"Remove-Item\b.*(-Recurse|-Force).*(Windows|System32|Program Files)"
    r"|"
    r"\bmkfs\."
    r"|"
    r"\bdd\s+if="
    r"|"
    r"cipher\s+/w:"
    r"|"
    r":\(\)\s*\{\s*:\|:&\s*\};:"
    r")"
)

# Explore-via-shell: dir /s through node_modules freezes Agent; type duplicates read_file.
_SHELL_EXPLORE_RE = re.compile(
    r"(?is)"
    r"("
    r"\bdir\b[^&\n|]*?/s\b"
    r"|\bGet-ChildItem\b[^&\n|]*?-Recurse\b"
    r"|\btree\s+[\"']?[A-Za-z]:"
    r"|\b(type|Get-Content|\bgc\b)\s+[\"']?[A-Za-z]:\\"
    r"|\b(type|Get-Content|\bgc\b)\s+[\"'][^\"']+\.(vue|ts|tsx|js|jsx|py|md|json|css|html)\b"
    r"|\bwhoami\b"
    r")"
)


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


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base or {})
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_profile() -> dict:
    """Load agent-profile.json, then merge agent-profile.local.json if present."""
    cfg: dict = {}
    if PROFILE.exists():
        try:
            cfg = json.loads(PROFILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cfg = {}
    if PROFILE_LOCAL.exists():
        try:
            local = json.loads(PROFILE_LOCAL.read_text(encoding="utf-8"))
            if isinstance(local, dict):
                cfg = _deep_merge(cfg, local)
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def resolve_profile_path(raw: str) -> Path:
    """Resolve agent-profile path entries relative to Juno HQ (supports ~)."""
    text = (raw or "").strip()
    if not text or text in {".", "./", "__HQ__"}:
        return HQ.resolve()
    if text in {"__DESKTOP__", "Desktop"}:
        return (Path.home() / "Desktop").resolve()
    # __DESKTOP__/subdir or __DESKTOP__\subdir
    for prefix in ("__DESKTOP__/", "__DESKTOP__\\"):
        if text.startswith(prefix):
            return (Path.home() / "Desktop" / text[len(prefix) :]).resolve()
    if text.startswith("~"):
        return Path(text).expanduser().resolve()
    p = Path(text)
    if not p.is_absolute():
        return (HQ / p).resolve()
    return p.resolve()


def load_projects() -> list[dict]:
    """Named project registry from agent-profile (± local)."""
    cfg = load_profile()
    raw = cfg.get("projects")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path_raw = str(item.get("path") or "").strip()
        if not path_raw:
            continue
        try:
            resolved = resolve_profile_path(path_raw)
        except OSError:
            continue
        out.append({
            "id": str(item.get("id") or resolved.name),
            "label": str(item.get("label") or item.get("id") or resolved.name),
            "path": path_raw,
            "resolved": str(resolved),
            "exists": resolved.exists(),
            "aliases": [str(a) for a in (item.get("aliases") or []) if str(a).strip()],
        })
    return out


def resolve_project_alias(name: str) -> dict | None:
    """Match user wording to a registered project (alias / id / folder name)."""
    q = (name or "").strip().strip('"').strip("'")
    if not q:
        return None
    # Filesystem paths must never go through alias substring matching
    # (e.g. ...\my-ai-agent\scripts would falsely match alias "my-ai-agent" → HQ root)
    if (
        re.match(r"^[a-zA-Z]:[\\/]", q)
        or q.startswith("\\\\")
        or "/" in q
        or "\\" in q
        or q in {".", "./", "..", ".\\"}
        or q.startswith("./")
        or q.startswith(".\\")
    ):
        return None
    q_lower = q.lower()
    projects = load_projects()
    # Exact alias / id / label / folder
    for proj in projects:
        keys = {proj["id"].lower(), Path(proj["resolved"]).name.lower()}
        keys |= {a.lower() for a in proj["aliases"]}
        label = (proj.get("label") or "").lower()
        if label:
            keys.add(label)
            # also match without spaces / punctuation-ish
            keys.add(re.sub(r"[\s/·]+", "", label))
        if q_lower in keys or q in proj["aliases"] or q == proj.get("label"):
            if proj["exists"]:
                return proj
    # Substring: user said「龙猫项目」and alias is「龙猫」
    for proj in projects:
        if not proj["exists"]:
            continue
        for a in proj["aliases"] + [proj["id"], proj.get("label") or ""]:
            a = str(a).strip()
            if len(a) >= 2 and (a.lower() in q_lower or q_lower in a.lower()):
                return proj
    return None


def tool_find_project(query: str = "") -> dict:
    """Resolve project by alias or list known projects (Cursor workspace switch-lite)."""
    q = (query or "").strip()
    if q:
        hit = resolve_project_alias(q)
        if hit:
            trust_user_path(hit["resolved"])
            listing = tool_list_dir(hit["resolved"], max_entries=50)
            return {
                "ok": True,
                "project": hit,
                "listing": listing,
                "hint": "后续 glob/grep/read 请用 project.resolved 作 path，不要只在 Juno 总部搜。",
            }
        # Fallback: shallow name search on Desktop / Documents / D:\
        matches: list[str] = []
        needles = [q, q.replace(" ", ""), q.lower()]
        for root in _broad_read_roots()[:6]:
            try:
                for child in root.iterdir():
                    if not child.is_dir():
                        continue
                    n = child.name.lower()
                    if any(nd.lower() in n for nd in needles if len(nd) >= 2):
                        matches.append(str(child))
                        if len(matches) >= 12:
                            break
            except OSError:
                continue
            if len(matches) >= 12:
                break
        return {
            "ok": False,
            "error": f"未在项目通讯录找到「{q}」",
            "disk_candidates": matches,
            "known_projects": [
                {"id": p["id"], "label": p["label"], "aliases": p["aliases"], "path": p["resolved"], "exists": p["exists"]}
                for p in load_projects()
            ],
            "hint": "把准确路径告诉我，或写入 config/agent-profile.local.json 的 projects[]。",
        }
    return {
        "ok": True,
        "projects": [
            {"id": p["id"], "label": p["label"], "aliases": p["aliases"], "path": p["resolved"], "exists": p["exists"]}
            for p in load_projects()
        ],
    }


def _tool_roots() -> list[Path]:
    cfg = load_profile()
    roots = (cfg.get("tools") or {}).get("roots") or ["."]
    out: list[Path] = []
    seen: set[str] = set()
    for r in roots:
        p = resolve_profile_path(str(r))
        key = str(p)
        if p.exists() and key not in seen:
            seen.add(key)
            out.append(p)
    for proj in load_projects():
        try:
            p = Path(proj["resolved"])
        except OSError:
            continue
        key = str(p)
        if p.exists() and key not in seen:
            seen.add(key)
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


_SKIP_DIR_NAMES = frozenset({
    "node_modules",
    ".git",
    ".next",
    "dist",
    "build",
    ".nuxt",
    ".output",
    "coverage",
    "__pycache__",
    ".venv",
    "venv",
    "target",
    ".turbo",
    ".cache",
    "vendor",
    "pnpm-store",
    ".pnpm-store",
})


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
    # Heavy dependency / build trees — never walk these for grep/glob resolve
    if any(part.lower() in _SKIP_DIR_NAMES for part in p.parts):
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


def _iter_files_fast(root: Path, *, max_files: int = 4000):
    """Walk files under root, skipping heavy dirs. Never materialize full tree."""
    stack = [root]
    n = 0
    while stack and n < max_files:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for ent in it:
                    name = ent.name
                    try:
                        if ent.is_dir(follow_symlinks=False):
                            if name.lower() in _SKIP_DIR_NAMES:
                                continue
                            stack.append(Path(ent.path))
                        elif ent.is_file(follow_symlinks=False):
                            yield Path(ent.path)
                            n += 1
                            if n >= max_files:
                                return
                    except OSError:
                        continue
        except OSError:
            continue


def _merge_roots(*groups: list[Path]) -> list[Path]:
    seen: set[str] = set()
    merged: list[Path] = []
    for group in groups:
        for p in group:
            key = str(p)
            if key not in seen:
                seen.add(key)
                merged.append(p)
    return merged


def trust_user_path(path_str: str) -> Path | None:
    """User explicitly @ / attached this path — allow read+write under it for this session."""
    raw = (path_str or "").strip().strip('"').strip("'").replace("/", "\\")
    if not raw or raw.startswith("git://") or raw.startswith("web://"):
        return None
    try:
        p = Path(raw)
        if not p.is_absolute():
            return None
        p = p.resolve()
    except OSError:
        return None
    if not p.exists():
        return None
    if _blocked_read_path(p):
        return None
    root = p if p.is_dir() else p.parent
    key = str(root)
    if not any(str(x) == key for x in _SESSION_TRUSTED_ROOTS):
        _SESSION_TRUSTED_ROOTS.append(root)
    return root


def trust_paths_from_turn(
    *,
    context_paths: list[dict] | None = None,
    message: str = "",
    attachments: list[dict] | None = None,
) -> list[str]:
    """Trust absolute paths the user attached or typed this turn."""
    trusted: list[str] = []
    candidates: list[str] = []
    for c in context_paths or []:
        candidates.append(str(c.get("path") or c.get("name") or "").strip())
    for a in attachments or []:
        candidates.append(str(a.get("source_path") or "").strip())
    candidates.extend(extract_paths_from_text(message or ""))
    for raw in candidates:
        if not raw:
            continue
        root = trust_user_path(raw)
        if root:
            trusted.append(str(root))
    return trusted


def _read_roots() -> list[Path]:
    policy = _read_policy()
    session = list(_SESSION_TRUSTED_ROOTS)
    if policy == "unrestricted":
        return _merge_roots(_drive_roots(), _tool_roots(), _broad_read_roots(), session)
    if policy == "broad":
        return _merge_roots(_tool_roots(), _broad_read_roots(), session)
    return _merge_roots(_tool_roots(), session)


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
    shell = _shell_policy()
    if not items:
        return "## 可读沙箱\n- （未配置 tools.roots）"
    lines = [f"## 可读范围（readPolicy={policy}）"]
    if policy == "unrestricted":
        lines.append("- **unrestricted 模式**：可读本机所有盘符下文件（仅屏蔽 Windows/Program Files 等系统目录）")
    elif policy == "broad":
        lines.append("- **broad 模式**：用户目录 + Desktop/文档/下载 + 已配置盘符 + 本会话用户 @ 的路径")
        if _SESSION_TRUSTED_ROOTS:
            lines.append("- **本会话信任**（用户明确附加）：")
            for p in _SESSION_TRUSTED_ROOTS[:6]:
                lines.append(f"  - `{p}`")
    else:
        lines.append("- **sandbox 模式**：仅限 tools.roots")
    for it in items[:12]:
        lines.append(f"- **{it['label']}** · `{it['path']}`")
    if len(items) > 12:
        lines.append(f"- …共 {len(items)} 个根")
    projects = load_projects()
    if projects:
        lines.append("- **项目通讯录**（用户说项目名时先 `find_project`，禁止只在总部盲 glob）：")
        for p in projects[:10]:
            mark = "✓" if p.get("exists") else "✗"
            aliases = " / ".join(p.get("aliases") or []) or p["id"]
            lines.append(f"  - {mark} **{p['label']}** · `{p['resolved']}` · 别名：{aliases}")
    lines.append(f"- **shellPolicy={shell}**：" + (
        "开放（近似 Cursor，仅拦高危破坏命令）" if shell == "open" else "白名单前缀匹配"
    ))
    lines.append("- 浏览/读代码：list_dir / glob / grep / read_file；**禁止** dir /s、type、Get-Content 代替")
    lines.append("- 写入范围见 tools.writeRoots（含 Desktop / 本会话信任路径）")
    lines.append("- 搜空：换根 / find_project / Desktop list_dir；改完：read_file + read_lints 再终答")
    return "\n".join(lines)


# Quoted paths first; bare paths may include spaces (e.g. C:\Users\solut xc\...).
# Old pattern used \s and truncated at the username space → "路径被截断了" death spiral.
PATH_IN_TEXT_RE = re.compile(
    r'"(?P<quoted>[A-Za-z]:\\[^"\n]+)"'
    r"|(?P<bare>[A-Za-z]:\\[^\n\"<>|*?]+)"
    r"|(?P<unix>/(?:[\w.\-]+/)*[\w.\-]+)"
)


def _refine_extracted_path(raw: str) -> str:
    """Trim run-on text after Windows paths; keep spaces inside real paths."""
    p = (raw or "").strip().strip('"').strip("'")
    p = p.rstrip(".,;:!?）)】\"'")
    # Cut at first CJK — common: `D:\proj 里改一下`
    for i, ch in enumerate(p):
        if "\u4e00" <= ch <= "\u9fff":
            p = p[:i].rstrip()
            break
    if not p:
        return p
    try:
        if Path(p).exists():
            return str(Path(p))
    except OSError:
        return p
    # Over-captured trailing English words: peel space-separated tokens until path exists
    cand = p
    while " " in cand:
        cand = cand.rsplit(" ", 1)[0].rstrip("\\/ ")
        if not cand:
            break
        try:
            if Path(cand).exists():
                return str(Path(cand))
        except OSError:
            break
    return p


def extract_paths_from_text(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for m in PATH_IN_TEXT_RE.finditer(text or ""):
        raw = m.group("quoted") or m.group("bare") or m.group("unix") or m.group(0)
        p = _refine_extracted_path(raw)
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
    """Resolve path: project alias → direct → HQ-relative → each tool root → unique basename rglob."""
    raw = (path_str or "").strip().strip('"').strip("'")
    if raw and raw not in (".", "./"):
        alias = resolve_project_alias(raw)
        if alias:
            trust_user_path(alias["resolved"])
            p = Path(alias["resolved"])
            if p.exists():
                return p
    fp = _resolve_allowed(path_str)
    if fp:
        return fp
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
    # Basename search — fast walk (skips node_modules/.git/…); never full rglob
    parts = [p for p in norm.split("\\") if p]
    if parts:
        tail = parts[-1]
        if "." in tail and len(parts) <= 3:
            found: list[Path] = []
            for root in _tool_roots():
                try:
                    for hit in _iter_files_fast(root, max_files=2500):
                        if hit.name != tail or _blocked_read_path(hit):
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
                if len(found) >= 6:
                    break
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
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
    raw = (path_str or "").strip().strip('"').strip("'")
    exists_on_disk = None
    try:
        cand = Path(raw.replace("/", "\\"))
        if cand.is_absolute():
            exists_on_disk = cand.exists()
            if exists_on_disk:
                hints.insert(
                    0,
                    "该绝对路径在磁盘上存在；用户已明确给出时应信任后重试，禁止让用户复制到桌面或粘贴文件内容",
                )
            drive = cand.drive
            if drive and not any(
                str(r.get("path") or "").upper().startswith(drive.upper()) for r in roots
            ):
                hints.insert(
                    0,
                    f"路径在 {drive} 盘且未在可读根内；把 `{drive}\\` 加入 broadReadRoots 或对本路径信任后重试，禁止建议复制到 C 盘",
                )
    except OSError:
        pass
    if raw and not Path(raw.replace("/", "\\")).is_absolute():
        for r in roots[:3]:
            hints.append(f"尝试绝对路径：{r['path']}\\{raw.replace('/', chr(92))}")
    return {
        "hint": " · ".join(hints[:4]),
        "allowed_roots": roots,
        "hq": str(HQ),
        "exists_on_disk": exists_on_disk,
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
    # Allow project alias as path
    raw_path = (path or ".").strip() or "."
    if raw_path not in {".", "./"}:
        alias = resolve_project_alias(raw_path)
        if alias:
            trust_user_path(alias["resolved"])
            path = alias["resolved"]
    fp = _smart_resolve(path or ".") or _smart_resolve(str(HQ))
    if not fp:
        out = {"ok": False, "error": f"路径不可访问: {path}"}
        out.update(_path_failure_hint(path))
        return out
    import shutil
    import subprocess

    def _finish(hits: list, *, engine: str, truncated: bool = False) -> dict:
        out: dict = {"ok": True, "hits": hits, "truncated": truncated, "engine": engine, "path": str(fp)}
        if not hits:
            out["search_empty"] = True
            out["hint"] = (
                "grep 无命中。换招：find_project → 换到正确项目根再 grep；"
                "或放宽正则 / glob 找文件名。禁止同一 path+pattern 死循环。"
            )
            out["next_tools"] = ["find_project", "glob", "list_dir", "search_index"]
        return out

    rg = shutil.which("rg")
    if rg:
        cmd = [rg, "-n", "--no-heading", "--color=never", "-m", str(max_hits)]
        # Skip dependency/build trees — otherwise rg on project root feels "stuck"
        for d in sorted(_SKIP_DIR_NAMES):
            cmd.extend(["--glob", f"!{d}/**", "--glob", f"!**/{d}/**"])
        if context:
            cmd.extend(["-C", str(context)])
        cmd.extend(["-e", pattern, str(fp)])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=12, encoding="utf-8", errors="replace")
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
                return _finish(hits, engine="rg", truncated=len(hits) >= max_hits)
        except (subprocess.TimeoutExpired, OSError):
            pass
    try:
        rx = re.compile(pattern, re.I)
    except re.error as e:
        return {"ok": False, "error": f"无效正则: {e}"}
    hits = []
    files = [fp] if fp.is_file() else _iter_files_fast(fp, max_files=2500)
    for f in files:
        try:
            if not f.is_file() or f.stat().st_size > 512_000:
                continue
        except OSError:
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
                    return _finish(hits, engine="python", truncated=True)
    return _finish(hits, engine="python", truncated=False)


def tool_glob(pattern: str, path: str = ".", *, max_matches: int = 40) -> dict:
    """Find files by glob. Empty → multi-root fallback + ladder hint (Cursor-like)."""
    pat = (pattern or "").strip() or "*"
    raw_path = (path or ".").strip() or "."

    # Allow path to be a project alias
    alias = resolve_project_alias(raw_path) if raw_path not in {".", "./", ""} else None
    if alias:
        trust_user_path(alias["resolved"])
        base = Path(alias["resolved"])
    else:
        base = _smart_resolve(raw_path) or _resolve_allowed(raw_path) or _resolve_allowed(".")
    if not base or not base.is_dir():
        out = {"ok": False, "error": f"目录不可访问: {path}", "pattern": pat}
        out.update(_path_failure_hint(raw_path))
        return out

    def _collect(root: Path) -> list[str]:
        import fnmatch

        found: list[str] = []
        try:
            # ** patterns: pathlib walks node_modules forever — use capped skip-walk
            if "**" in pat:
                for item in _iter_files_fast(root, max_files=3000):
                    rel = str(item.relative_to(root)).replace("\\", "/")
                    if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(item.name, pat):
                        found.append(str(item))
                        if len(found) >= max_matches:
                            break
            else:
                for item in root.glob(pat):
                    if any(part.lower() in _SKIP_DIR_NAMES for part in item.parts):
                        continue
                    found.append(str(item))
                    if len(found) >= max_matches:
                        break
        except OSError:
            pass
        return found

    matches = _collect(base)
    scanned = [str(base)]

    # Empty under HQ/"." → scan other project/tool roots (don't die in my-ai-agent only)
    # Skip expensive **/ multi-root fan-out (node_modules monsters); rely on find_project instead
    if (
        not matches
        and "**" not in pat
        and (raw_path in {".", "./", ""} or base.resolve() == HQ.resolve())
    ):
        for root in _tool_roots():
            if root.resolve() == base.resolve():
                continue
            extra = _collect(root)
            scanned.append(str(root))
            if extra:
                matches.extend(extra)
                if len(matches) >= max_matches:
                    matches = matches[:max_matches]
                    break

    result: dict = {
        "ok": True,
        "path": str(base),
        "pattern": pat,
        "matches": matches,
        "scanned_roots": scanned[:8],
    }
    if "**" in pat:
        result["hint_explore"] = (
            "根目录 ** glob 很慢且易空转。优先：list_dir 顶层 → 对 frontend/src 等子目录 glob；"
            "禁止对同一 pattern+path 重复 glob。"
        )
    if not matches:
        result["search_empty"] = True
        result["hint"] = (
            "glob 无匹配。换招：① find_project(项目名) ② list_dir Desktop/Documents "
            "③ 换 **/*name* 或更宽 pattern ④ grep 内容 ⑤ 问用户确切路径。"
            "禁止只在 Juno 总部重复同一 pattern。"
        )
        result["next_tools"] = ["find_project", "list_dir", "grep", "search_index"]
        result["known_projects"] = [
            {"label": p["label"], "path": p["resolved"], "aliases": p["aliases"]}
            for p in load_projects() if p.get("exists")
        ][:8]
    return result


def tool_search_index(query: str, *, top_k: int = 6) -> dict:
    import juno_index

    q = (query or "").strip()
    # If query mentions a known project, trust its root for later tools
    proj = resolve_project_alias(q)
    if proj:
        trust_user_path(proj["resolved"])
    hits = juno_index.search(q, top_k=top_k)
    result: dict = {"ok": True, "hits": hits, "query": q}
    if proj:
        result["matched_project"] = {
            "label": proj["label"],
            "path": proj["resolved"],
            "hint": "索引可能未含该项目；请用 glob/grep 在 project.path 下搜，勿只信 search_index。",
        }
    if not hits:
        result["search_empty"] = True
        result["hint"] = (
            "语义索引无命中（索引默认主要在 Juno 总部）。"
            "下一步：find_project → glob/grep 到正确项目根；或 list_dir Desktop。"
        )
        result["next_tools"] = ["find_project", "glob", "grep", "list_dir"]
    return result


_SESSION_ID: str | None = None
EDIT_ROOT = HQ / "memory" / "session-edits"


def set_session_context(session_id: str | None) -> None:
    global _SESSION_ID, _SESSION_TRUSTED_ROOTS
    new_id = (session_id or "").strip() or None
    if new_id != _SESSION_ID:
        _SESSION_TRUSTED_ROOTS = []
    _SESSION_ID = new_id


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
        "verify_hint": (
            "改完自检：read_file 核对本文件改动区间；"
            "若是 .py/.ts/.js/.vue/.tsx 再 read_lints；"
            "用户要跑通时 run_shell。禁止未核对就说「好了」。"
        ),
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
        return {
            "ok": True,
            "path": str(fp),
            "patched": True,
            "bytes": len(content.encode("utf-8")),
            "backup": backup,
            "verify_hint": (
                "改完自检：read_file 核对；代码文件再 read_lints；"
                "禁止未核对就说「好了」。"
            ),
        }
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


_THINK_LOG: list[dict] = []


def tool_think(
    thought: str,
    *,
    thought_number: int = 1,
    total_thoughts: int = 3,
    next_thought_needed: bool = True,
    is_revision: bool = False,
    revises_thought: int | None = None,
) -> dict:
    """Scratchpad for sequential reasoning (official Sequential Thinking inspired)."""
    global _THINK_LOG
    text = (thought or "").strip().replace("\ufffd", "")
    if not text:
        return {"ok": False, "error": "think 需要 thought 文本"}
    try:
        n = max(1, int(thought_number or 1))
        total = max(n, int(total_thoughts or 3))
    except (TypeError, ValueError):
        n, total = 1, 3
    entry = {
        "thought_number": n,
        "total_thoughts": total,
        "thought": text[:2000],
        "is_revision": bool(is_revision),
        "revises_thought": revises_thought,
        "next_thought_needed": bool(next_thought_needed),
    }
    _THINK_LOG.append(entry)
    _THINK_LOG = _THINK_LOG[-40:]
    gate = (
        "开口前：①信息盘点是否覆盖用户给出的每条事实/约束（有未用项→继续 think）；"
        "②推荐会不会让原目标破产；③「大概率」是否仍是假设并考虑过低成本验证。"
    )
    if next_thought_needed:
        guide = "继续调用 think 下一步；可修订前序结论。尚未完成，先不要终答用户。"
    else:
        guide = "思考链结束：现在用简洁结论回复用户；不要朗读本草稿。"
    return {
        "ok": True,
        "recorded": True,
        "thought_number": n,
        "total_thoughts": total,
        "next_thought_needed": bool(next_thought_needed),
        "history_len": len(_THINK_LOG),
        "goal_gate": gate,
        "next": guide,
    }


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


def _shell_policy() -> str:
    """allowlist (default legacy) | open (Cursor-like: deny only dangerous)."""
    return str((load_profile().get("tools") or {}).get("shellPolicy") or "allowlist").strip().lower()


def _shell_denied(cmd: str) -> bool:
    return bool(_SHELL_DENY_RE.search(cmd or ""))


def _shell_explore_misuse(cmd: str) -> str | None:
    """Return hint if shell is being used as a slow substitute for list/read/glob."""
    c = cmd or ""
    if not _SHELL_EXPLORE_RE.search(c):
        return None
    if re.search(r"(?is)\bdir\b[^&\n|]*?/s\b|\bGet-ChildItem\b[^&\n|]*?-Recurse\b|\btree\s+", c):
        return (
            "禁止用 dir /s / Get-ChildItem -Recurse / tree 扫项目根（会钻进 node_modules，极慢）。"
            "改用 list_dir（浅列）或 glob/grep（已跳过依赖目录）。"
        )
    if re.search(r"(?is)\b(type|Get-Content|\bgc\b)\b", c):
        return (
            "禁止用 type/Get-Content 读源码。改用 read_file(path, offset, limit)，路径用完整绝对路径并加引号。"
        )
    if re.search(r"(?is)\bwhoami\b", c):
        return "不必 whoami；继续用 list_dir/read_file/glob 完成用户任务。"
    return "请用 list_dir / glob / read_file，不要用 shell 代替文件探索。"


def _shell_allowed(cmd: str) -> bool:
    c = (cmd or "").strip()
    if not c:
        return False
    if _shell_denied(c):
        return False
    if _shell_policy() == "open":
        return True
    cfg = load_profile()
    allow = (cfg.get("tools") or {}).get("shellAllowlist") or []
    segments = re.split(r"\s*&&\s*|\s*;\s*", c)
    if len(segments) == 1:
        return _segment_shell_allowed(c, allow)
    return all(_segment_shell_allowed(seg, allow) for seg in segments)


def _write_roots() -> list[Path]:
    cfg = load_profile()
    raw = (cfg.get("tools") or {}).get("writeRoots") or ["memory", "knowledge"]
    out: list[Path] = []
    seen: set[str] = set()
    for r in raw:
        p = resolve_profile_path(str(r))
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    # Registered projects + session-trusted paths are writable this session
    for proj in load_projects():
        try:
            p = Path(proj["resolved"])
        except OSError:
            continue
        key = str(p)
        if p.exists() and key not in seen:
            seen.add(key)
            out.append(p)
    for p in _SESSION_TRUSTED_ROOTS:
        key = str(p)
        if key not in seen:
            seen.add(key)
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
    r"("
    r"npm\s+(run|start|run-script)\b|pnpm\s+(run|dev|start|preview)\b|yarn\s+(run|dev|start)\b|"
    r"npx\s+|electron\b|vite\b|nuxt\b|next\s+dev|nodemon\b|webpack\s+serve|"
    r"tsx\s+watch|ts-node-dev\b|uvicorn\b|flask\s+run|django(\.exe)?\s+runserver|"
    r"python\s+.*\b(serve|uvicorn|flask)\b|"
    r"\bdev\b.*(--|--host|--port)|watch\s+src"
    r")",
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
    # Brief settle so first Vite/Nuxt lines often appear — never claim "started" from spawn alone
    time.sleep(2.0)
    peek = "".join(lines[-50:]).strip()
    early_exit = bool(_BG_JOBS[job_id].get("done"))
    return {
        "ok": not early_exit,
        "background": True,
        "integrated": True,
        "job_id": job_id,
        "pid": proc.pid,
        "command": command,
        "cwd": str(cwd),
        "early_exit": early_exit,
        "exit_code": _BG_JOBS[job_id].get("code"),
        "output": (
            f"已后台启动 job={job_id} pid={proc.pid}"
            + ("（进程已退出，启动失败）" if early_exit else "")
            + ("\n--- 首批日志 ---\n" + peek if peek else "\n（2s 内尚无日志）")
            + "\n下一步：shell_job 读后续日志；netstat/curl 确认端口监听后才能对用户说「已启动」。"
        ),
        "stdout": peek[:4000],
        "hint": "禁止仅凭后台 spawn 就报 ✅。必须验证端口/HTTP。",
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
    explore_hint = _shell_explore_misuse(command)
    if explore_hint:
        return {
            "ok": False,
            "error": "已拦截：请用专用文件工具，不要用 shell 扫盘/读文件",
            "hint": explore_hint,
            "next_tools": ["list_dir", "glob", "grep", "read_file", "find_project"],
            "command": command,
        }
    if not _shell_allowed(command):
        if _shell_denied(command):
            return {
                "ok": False,
                "error": "命令匹配高危破坏模式，已拒绝",
                "hint": "shellPolicy=open 仍禁止 format/rm 根目录/抹盘等；换更安全的写法",
                "command": command,
            }
        allow = (load_profile().get("tools") or {}).get("shellAllowlist") or []
        preview = ", ".join(str(a).strip() for a in allow[:12])
        return {
            "ok": False,
            "error": "命令不在白名单，已拒绝",
            "hint": f"允许前缀示例：{preview}… 或把 tools.shellPolicy 设为 open。长驻 dev 用 run_shell + cwd",
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
    {"name": "find_project", "desc": "按别名定位项目根（龙猫/totoro/Juno…）；空 query 列出通讯录", "args": {"query": "str?"}},
    {"name": "glob", "desc": "按 glob 模式找文件（可跨项目根；path 可用项目别名）", "args": {"pattern": "str", "path": "str?"}},
    {"name": "grep", "desc": "在路径下正则搜索（path 可用项目别名）", "args": {"pattern": "str", "path": "str?"}},
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
    {
        "name": "think",
        "desc": (
            "分步思考草稿（Sequential Thinking）。回答二选一/生活建议/权衡前先调用；"
            "可多次修订；确认目标自洽后再对用户作答。勿把草稿原文念给用户。"
        ),
        "args": {
            "thought": "str",
            "thought_number": "int?",
            "total_thoughts": "int?",
            "next_thought_needed": "bool?",
            "is_revision": "bool?",
            "revises_thought": "int?",
        },
    },
    {"name": "run_shell", "desc": "运行白名单 shell；pnpm/npm/vite/nuxt/tsx watch 等长驻命令自动后台，返回 job_id", "args": {"command": "str", "cwd": "str?"}},
    {
        "name": "shell_job",
        "desc": "读取后台 run_shell 任务日志（用 job_id）。启动服务后必须调它看是否真起来，再 curl/netstat 验证。",
        "args": {"job_id": "str", "offset": "int?"},
    },
    {"name": "task", "desc": "启动子代理 explore/shell（Cursor Task 同款）", "args": {"action": "str", "kind": "str?", "prompt": "str?", "tasks": "list?"}},
    {"name": "mcp_call", "desc": "调用入站 MCP 工具", "args": {"server": "str", "tool": "str", "arguments": "str?"}},
]


def tool_schemas(*, only: set[str] | None = None) -> list[dict]:
    """OpenAI-compatible tool schemas for native function calling."""
    schemas = []
    for t in TOOL_DEFS:
        if only is not None and t.get("name") not in only:
            continue
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

    for root in _read_roots():
        try:
            for fp in _iter_files_fast(root, max_files=2000):
                try:
                    if not fp.is_file() or fp.stat().st_size > 2_000_000:
                        continue
                except OSError:
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
    if name == "find_project":
        return tool_find_project(args.get("query") or args.get("name") or "")
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
    if name == "think":
        rev = args.get("revises_thought")
        try:
            rev_i = int(rev) if rev not in (None, "") else None
        except (TypeError, ValueError):
            rev_i = None
        nxt = args.get("next_thought_needed")
        if nxt is None:
            nxt = True
        return tool_think(
            args.get("thought") or "",
            thought_number=int(args.get("thought_number") or 1),
            total_thoughts=int(args.get("total_thoughts") or 3),
            next_thought_needed=bool(nxt),
            is_revision=bool(args.get("is_revision")),
            revises_thought=rev_i,
        )
    if name == "run_shell":
        return tool_run_shell(args.get("command", ""), cwd=args.get("cwd"))
    if name == "shell_job":
        return get_shell_job(args.get("job_id") or "", offset=int(args.get("offset") or 0))
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
