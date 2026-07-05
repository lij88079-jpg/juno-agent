#!/usr/bin/env python3
"""Juno skill router — load Cursor agent skills + workspace rules into prompts."""
from __future__ import annotations

import json
import re
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
PROFILE = HQ / "config" / "agent-profile.json"
SKILLS_DIR = HQ / ".cursor" / "skills"
RULES_DIR = HQ / ".cursor" / "rules"
AGENTS = HQ / "AGENTS.md"
USER_RULES = HQ / "knowledge" / "juno-user-rules.md"

EXPLICIT_SKILL_RE = re.compile(
    r"@(?:my-core-agent|agent-(?:chat|research|writing|coding|memory))\b",
    re.I,
)
MEMORY_RE = re.compile(
    r"记住|学习对话|总结聊天|更新记忆|agent-memory|remember\s+from|提炼对话",
    re.I,
)
WRITING_RE = re.compile(
    r"写作|润色|翻译|改写|文案|邮件|剧本|扩写|缩写|proofread|translate|rewrite",
    re.I,
)
RESEARCH_RE = re.compile(
    r"调研|研究一下|是什么|为什么|对比|总结资料|解释.{0,6}概念|学习.{0,4}原理|"
    r"有什么区别|优缺点|科普|入门|overview|compare",
    re.I,
)
GIT_COMMIT_RE = re.compile(r"git\s+commit|提交代码|帮我提交|create\s+commit", re.I)

INTENT_TO_SKILL = {
    "casual": "agent-chat",
    "frustrated": "agent-chat",
    "general": "agent-chat",
    "chat": "agent-chat",
    "research": "agent-research",
    "writing": "agent-writing",
    "coding": "agent-coding",
    "technical": "agent-coding",
    "design": "agent-coding",
    "shell": "agent-coding",
    "file": "agent-coding",
    "memory": "agent-memory",
}


def load_profile() -> dict:
    if PROFILE.exists():
        return json.loads(PROFILE.read_text(encoding="utf-8"))
    return {}


def _strip_frontmatter(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("---"):
        parts = t.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return t


def _clip(text: str, n: int) -> str:
    t = (text or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _skill_path(skill_id: str) -> Path | None:
    sid = skill_id.replace("@", "").strip()
    if sid == "my-core-agent":
        for candidate in (
            SKILLS_DIR / "my-core-agent" / "SKILL.md",
            SKILLS_DIR / "my-core-agent" / "my-core-agent" / "SKILL.md",
        ):
            if candidate.exists():
                return candidate
        return None
    p = SKILLS_DIR / sid / "SKILL.md"
    return p if p.exists() else None


def load_skill_body(skill_id: str) -> str:
    fp = _skill_path(skill_id)
    if not fp:
        return ""
    return _strip_frontmatter(fp.read_text(encoding="utf-8"))


def detect_explicit_skill(user_message: str) -> str | None:
    m = EXPLICIT_SKILL_RE.search(user_message or "")
    if not m:
        return None
    tag = m.group(0).lower().lstrip("@")
    if tag == "my-core-agent":
        return "my-core-agent"
    return tag


def skill_for_intent(intent: str) -> str:
    return INTENT_TO_SKILL.get(intent, "agent-chat")


def build_skill_inject(
    intent: str,
    user_message: str = "",
    *,
    compact: bool = False,
) -> str:
    """Return skill block for current intent (explicit @ wins)."""
    explicit = detect_explicit_skill(user_message)
    skill_id = explicit or skill_for_intent(intent)
    body = load_skill_body(skill_id)
    if not body:
        return ""

    if compact:
        body = _clip(body, 900)
        header = f"## 当前 Skill · {skill_id}（精简）"
    else:
        body = _clip(body, 4500)
        header = f"## 当前 Skill · {skill_id}"

    if GIT_COMMIT_RE.search(user_message or "") and intent in ("shell", "coding", "technical"):
        body += "\n\n### Git 提交提醒\n用户可能要 commit → 先 status/diff/log，仅用户明确要求才 commit。"

    return f"{header}\n\n{body}"


def _load_inject_block(doc: Path, tag: str) -> str:
    if not doc.exists():
        return ""
    text = doc.read_text(encoding="utf-8")
    start, end = f"<!-- INJECT:{tag} -->", f"<!-- END:{tag} -->"
    if start not in text or end not in text:
        return ""
    return text.split(start, 1)[1].split(end, 1)[0].strip()


def load_user_rules_inject(*, compact: bool = False) -> str:
    tag = "compact" if compact else "full"
    block = _load_inject_block(USER_RULES, tag)
    return block or ("## 用户规则\n不确定不编造 · 最小 diff · 用户要求才 commit")


def load_agents_inject(*, compact: bool = False) -> str:
    if not AGENTS.exists():
        return ""
    body = AGENTS.read_text(encoding="utf-8").strip()
    if compact:
        return _clip(
            "## AGENTS 协议（摘要）\n"
            + body.replace("#", "").replace("##", "·")[:600],
            650,
        )
    return "## AGENTS 运行协议\n\n" + body


def load_rules_inject(*, compact: bool = False) -> str:
    if not RULES_DIR.exists():
        return ""
    parts: list[str] = []
    for fp in sorted(RULES_DIR.glob("*.mdc")):
        raw = fp.read_text(encoding="utf-8")
        body = _strip_frontmatter(raw)
        if compact:
            body = _clip(body, 400)
        parts.append(f"### 规则 · {fp.stem}\n{body}")
    if not parts:
        return ""
    header = "## 工作区规则（.cursor/rules）"
    joined = "\n\n".join(parts)
    return _clip(f"{header}\n\n{joined}", 1200 if compact else 8000)


def load_core_router_inject(*, compact: bool = False) -> str:
    body = load_skill_body("my-core-agent")
    if not body:
        return ""
    if compact:
        return _clip("## 总路由（my-core-agent 摘要）\n" + body, 500)
    return "## 总路由（my-core-agent）\n\n" + _clip(body, 2000)


def load_daily_memory_inject(*, compact: bool = False) -> str:
    from datetime import datetime
    daily_dir = HQ / "memory" / "daily"
    if not daily_dir.exists():
        return ""
    today = datetime.now().strftime("%Y-%m-%d")
    fp = daily_dir / f"{today}.md"
    if not fp.exists():
        return ""
    body = fp.read_text(encoding="utf-8").strip()
    if compact:
        body = _clip(body, 500)
    return f"## 今日日志（{today}）\n{body}"


def load_tools_heartbeat_inject(*, compact: bool = False) -> str:
    parts = []
    for name, title in (("TOOLS.md", "工具笔记"), ("HEARTBEAT.md", "心跳清单")):
        fp = HQ / name
        if fp.exists():
            body = _clip(fp.read_text(encoding="utf-8").strip(), 400 if compact else 2000)
            parts.append(f"### {title}\n{body}")
    return "\n\n".join(parts)


def load_cursor_read_tools_inject(*, compact: bool = False) -> str:
    fp = HQ / "knowledge" / "cursor-read-tools.md"
    if not fp.exists():
        return ""
    text = fp.read_text(encoding="utf-8")
    tag = "compact" if compact else "agent"
    start, end = f"<!-- INJECT:{tag} -->", f"<!-- END:{tag} -->"
    if start not in text or end not in text:
        return ""
    return text.split(start, 1)[1].split(end, 1)[0].strip()


def load_cursor_agent_full_inject(*, compact: bool = False) -> str:
    fp = HQ / "knowledge" / "cursor-agent-full.md"
    if not fp.exists():
        return ""
    text = fp.read_text(encoding="utf-8")
    tag = "compact" if compact else "agent"
    start, end = f"<!-- INJECT:{tag} -->", f"<!-- END:{tag} -->"
    if start not in text or end not in text:
        return _clip(text.strip(), 1200 if compact else 6000)
    block = text.split(start, 1)[1].split(end, 1)[0].strip()
    return _clip(block, 900 if compact else 6000)


def build_workspace_protocol(*, compact: bool = False, mode: str = "chat") -> str:
    """AGENTS + rules + user-rules — always-on protocol layer."""
    chunks = [
        load_agents_inject(compact=compact),
        load_rules_inject(compact=compact),
        load_user_rules_inject(compact=compact),
        load_daily_memory_inject(compact=compact),
        load_tools_heartbeat_inject(compact=compact),
    ]
    if mode in ("agent", "plan") or not compact:
        read_tools = load_cursor_read_tools_inject(compact=compact)
        if read_tools:
            chunks.append(read_tools)
        full = load_cursor_agent_full_inject(compact=compact)
        if full:
            chunks.append(full)
    if not compact:
        chunks.append(load_core_router_inject(compact=False))
    return "\n\n".join(c for c in chunks if c)


def list_skills() -> list[dict]:
    cfg = load_profile()
    mapping = cfg.get("skills") or {}
    items = []
    for key, sid in mapping.items():
        fp = _skill_path(sid)
        items.append({"id": sid, "role": key, "loaded": bool(fp)})
    return items


def list_inject_layers(*, mode: str = "agent") -> list[dict]:
    """Report which inject blocks are available (for UI / debug)."""
    import juno_index
    import juno_mcp_client

    def on(path: Path) -> bool:
        return path.exists()

    daily = HQ / "memory" / "daily"
    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    idx = juno_index.index_status()
    mcp_on = bool(juno_mcp_client.format_mcp_for_prompt())
    ide_on = on(HQ / "memory" / "ide-context.json")
    return [
        {"id": "soul", "label": "SOUL", "active": on(HQ / "SOUL.md")},
        {"id": "user", "label": "USER", "active": on(HQ / "USER.md")},
        {"id": "memory", "label": "MEMORY", "active": on(HQ / "MEMORY.md")},
        {"id": "caps", "label": "听说读写", "active": on(HQ / "knowledge" / "juno-capabilities.md")},
        {"id": "agents", "label": "AGENTS", "active": on(AGENTS)},
        {"id": "rules", "label": "Rules", "active": RULES_DIR.exists() and any(RULES_DIR.glob("*.mdc"))},
        {"id": "orchestrator", "label": "Auto编排", "active": on(HQ / "knowledge" / "auto-orchestration.md")},
        {"id": "brain_chain", "label": "工作链", "active": on(HQ / "knowledge" / "cursor-brain-chain.md")},
        {"id": "workflow", "label": "工作流", "active": on(HQ / "knowledge" / "juno-workflow.md")},
        {"id": "thinking", "label": "思考", "active": on(HQ / "knowledge" / "juno-thinking-design.md")},
        {"id": "cursor_tools", "label": "读工具", "active": on(HQ / "knowledge" / "cursor-read-tools.md")},
        {"id": "cursor_agent", "label": "Agent协议", "active": on(HQ / "knowledge" / "cursor-agent-full.md")},
        {"id": "daily", "label": "今日日志", "active": on(daily / f"{today}.md")},
        {"id": "tools_hb", "label": "TOOLS/HB", "active": on(HQ / "TOOLS.md") or on(HQ / "HEARTBEAT.md")},
        {"id": "index", "label": "索引", "active": bool(idx.get("chunks")), "detail": str(idx.get("chunks") or 0)},
        {"id": "ide_ctx", "label": "IDE", "active": ide_on},
        {"id": "mcp", "label": "MCP", "active": mcp_on},
        {"id": "plan", "label": "Plan块", "active": bool(_load_inject_block(HQ / "knowledge" / "juno-capabilities.md", "full-plan"))},
    ]
