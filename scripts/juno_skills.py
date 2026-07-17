#!/usr/bin/env python3
"""Juno skill router — load Cursor agent skills + workspace rules into prompts."""
from __future__ import annotations

import json
import re
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
PROFILE = HQ / "config" / "agent-profile.json"
CC_SKILLS_CFG = HQ / "config" / "cc-skills.json"
SKILLS_DIR = HQ / ".cursor" / "skills"
RULES_DIR = HQ / ".cursor" / "rules"
AGENTS = HQ / "AGENTS.md"
USER_RULES = HQ / "knowledge" / "juno-user-rules.md"

EXPLICIT_SKILL_RE = re.compile(
    r"@(?:my-core-agent|agent-(?:chat|research|writing|coding|memory)|"
    r"pr-review-expert|focused-fix|codebase-onboarding|spec-driven-workflow|"
    r"deep-research|doc-coauthoring|frontend-design|mcp-builder|"
    r"skill-creator|internal-comms|webapp-testing|web-artifacts-builder|"
    r"pdf|docx|pptx|xlsx|sequential-thinking|information-inventory|chat-visuals)\b",
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
    "hostile": "agent-chat",
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

CC_SKILL_CLIP = {
    "deep-research": 1600,
    "pr-review-expert": 1400,
    "focused-fix": 1500,
    "spec-driven-workflow": 1400,
    "codebase-onboarding": 1400,
    "doc-coauthoring": 1300,
    "frontend-design": 1200,
    "mcp-builder": 1300,
    "skill-creator": 1300,
    "internal-comms": 1100,
    "webapp-testing": 1200,
    "web-artifacts-builder": 1200,
    "pdf": 1200,
    "docx": 1200,
    "pptx": 1200,
    "xlsx": 1200,
    "sequential-thinking": 900,
    "information-inventory": 900,
    "chat-visuals": 900,
}
DEFAULT_CC_CLIP = 1400
DEFAULT_NATIVE_CLIP = 1000
NATIVE_SKILL_CLIP = {
    "agent-chat": 0,  # tone lives in instinct — never auto-dump chat craft
    "agent-research": 1200,
    "agent-writing": 1100,
    "agent-coding": 1300,
    "agent-memory": 900,
}

# Idle chat/identity: DS + instinct. Work intents get capability playbooks.
LIGHT_INTENTS_NO_SKILL = frozenset({
    "meta", "casual", "frustrated", "hostile", "general",
})


def load_cc_manifest() -> dict:
    if not CC_SKILLS_CFG.exists():
        return {"imports": [], "fallback": dict(INTENT_TO_SKILL)}
    try:
        return json.loads(CC_SKILLS_CFG.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"imports": [], "fallback": dict(INTENT_TO_SKILL)}


def cc_skill_entries() -> list[dict]:
    return list(load_cc_manifest().get("imports") or [])


def fallback_skill_for_intent(intent: str) -> str:
    fb = load_cc_manifest().get("fallback") or {}
    return fb.get(intent) or INTENT_TO_SKILL.get(intent, "agent-chat")


def _keyword_score(text: str, keywords: list[str]) -> int:
    t = (text or "").lower()
    score = 0
    for kw in keywords:
        k = (kw or "").strip().lower()
        if k and k in t:
            score += 2 if len(k) > 4 else 1
    return score


def resolve_skill_id(intent: str, user_message: str = "") -> str:
    """Pick one skill: explicit @ > keyword CC match > intent CC > Juno fallback."""
    explicit = detect_explicit_skill(user_message)
    if explicit:
        return explicit

    msg = user_message or ""
    best_id = ""
    best_score = 0
    for entry in cc_skill_entries():
        sid = entry.get("id") or ""
        if not sid or not _skill_path(sid):
            continue
        intents = entry.get("intents") or []
        keywords = entry.get("keywords") or []
        score = _keyword_score(msg, keywords)
        if intent in intents:
            score += 1
        if score > best_score:
            best_score = score
            best_id = sid

    # intent(+1)+keyword(+1) must beat intent-only first-match (pr-review before focused-fix)
    if best_score >= 2 and best_id:
        return best_id

    # Intent-only: prefer native coding/research fallbacks over first CC import
    if intent in ("technical", "coding", "shell", "file", "design"):
        fb = fallback_skill_for_intent(intent)
        if fb and _skill_path(fb):
            return fb
    if intent == "research":
        for sid in ("deep-research", "agent-research"):
            if _skill_path(sid):
                return sid

    for entry in cc_skill_entries():
        sid = entry.get("id") or ""
        intents = entry.get("intents") or []
        if sid and intent in intents and _skill_path(sid):
            return sid

    return fallback_skill_for_intent(intent)


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
    body = _strip_frontmatter(fp.read_text(encoding="utf-8"))
    # Optional Juno overlay (keeps upstream SKILL.md intact)
    juno = fp.parent / "JUNO.md"
    if juno.is_file():
        extra = juno.read_text(encoding="utf-8").strip()
        if extra:
            body = f"{body}\n\n---\n## Juno 适配\n\n{extra}"
    return body


def detect_explicit_skill(user_message: str) -> str | None:
    m = EXPLICIT_SKILL_RE.search(user_message or "")
    if m:
        tag = m.group(0).lower().lstrip("@")
        if _skill_path(tag):
            return tag
    for m in re.finditer(r"@([\w-]+)", user_message or ""):
        sid = m.group(1).lower()
        if _skill_path(sid):
            return sid
    return None


def skill_for_intent(intent: str, user_message: str = "") -> str:
    return resolve_skill_id(intent, user_message)


def _cc_keywords_for(skill_id: str) -> list[str]:
    for entry in cc_skill_entries():
        if entry.get("id") == skill_id:
            return list(entry.get("keywords") or [])
    return []


def load_skill_assist(skill_id: str, *, explicit: bool = False) -> str:
    """Capability tip — JUNO.md first; full SKILL when user @-mentions.

    Purpose: raise research/debug/code quality (a leading chat model/Juno-style workflows),
    not stew the prompt on every casual turn.
    """
    sid = (skill_id or "").replace("@", "").strip()
    if not sid:
        return ""
    root = SKILLS_DIR / sid
    if sid == "my-core-agent":
        root = next(
            (p.parent for p in (
                SKILLS_DIR / "my-core-agent" / "SKILL.md",
                SKILLS_DIR / "my-core-agent" / "my-core-agent" / "SKILL.md",
            ) if p.exists()),
            root,
        )
    juno = root / "JUNO.md"
    skill = root / "SKILL.md"
    if not skill.exists() and sid == "my-core-agent":
        return ""
    if explicit:
        return load_skill_body(sid)
    if juno.is_file():
        return juno.read_text(encoding="utf-8").strip()
    if skill.is_file():
        return _clip(_strip_frontmatter(skill.read_text(encoding="utf-8")), 900)
    return ""


def build_skill_inject(
    intent: str,
    user_message: str = "",
    *,
    compact: bool = False,
) -> str:
    """Capability assist for hard turns — gather info, reason thoroughly, then act.

    Like a leading chat model/a leading assistant advanced workflows: raise the floor on research / debug / code.
    NOT a chat personality script. Light identity/hi turns get nothing.
    """
    explicit = detect_explicit_skill(user_message)
    # Chat / identity: DS + instinct only
    if not explicit and intent in LIGHT_INTENTS_NO_SKILL:
        return ""

    skill_id = resolve_skill_id(intent, user_message)
    # agent-chat must never auto-inject (redundant personality soup)
    if not explicit and skill_id == "agent-chat":
        return ""

    body = load_skill_assist(skill_id, explicit=bool(explicit))
    if not body:
        return ""

    is_cc = skill_id in {e.get("id") for e in cc_skill_entries()}
    if explicit:
        if compact:
            limit = 1600 if is_cc else 1200
        elif is_cc:
            limit = min(CC_SKILL_CLIP.get(skill_id, DEFAULT_CC_CLIP) * 2, 3200)
        else:
            limit = min(max(NATIVE_SKILL_CLIP.get(skill_id, DEFAULT_NATIVE_CLIP), 800) * 2, 2400)
        header = f"## 能力辅助 · {skill_id}（用户明确 @）"
    else:
        if compact:
            limit = 900 if is_cc else 700
        elif is_cc:
            limit = CC_SKILL_CLIP.get(skill_id, DEFAULT_CC_CLIP)
        else:
            limit = NATIVE_SKILL_CLIP.get(skill_id, DEFAULT_NATIVE_CLIP) or DEFAULT_NATIVE_CLIP
        header = f"## 能力辅助 · {skill_id}"

    body = _clip(body, limit)
    frame = (
        "\n\n**【用法】**Compact advanced workflow assist: "
        "帮你更全面地搜集信息、拆问题、改代码。"
        "按需用方法，不要朗读手册；人格与口吻仍听本能，独立思考优先。"
    )

    if GIT_COMMIT_RE.search(user_message or "") and intent in ("shell", "coding", "technical"):
        body += "\n\n### Git\n用户可能要 commit → 先 status/diff/log，仅明确要求才 commit。"

    out = f"{header}\n\n{body}{frame}"

    viz_kws = _cc_keywords_for("chat-visuals")
    viz_hit = bool(
        viz_kws
        and (
            _keyword_score(user_message, viz_kws) >= 1
            or re.search(r"画(一张|个|一下)?|详解图|示意图|结构图|流程图|架构图|思维导图", user_message or "")
        )
    )
    if skill_id != "chat-visuals" and viz_hit:
        viz = load_skill_assist("chat-visuals", explicit=False)
        if viz:
            out += (
                "\n\n## 能力辅助 · chat-visuals\n\n"
                + _clip(viz, 700 if compact else 1000)
                + "\n\n要图时答复须含可渲染 ```mermaid / ```chart；查清再画，别只口头形容。"
            )
    return out


def format_deliberation_skills(
    *,
    allow_other_tools: bool = False,
    compact: bool = False,
) -> str:
    """Capability assist for situational/trade-off turns — fuller thinking, not scripts."""
    parts: list[str] = [
        "## 能力辅助 · 想得更全面\n"
        "情景/二选一/多约束：先盘点事实·约束·未知·成功标准，再结论。"
        "目标是想周全，不是背 skill 原文给用户。"
    ]
    lim = 600 if compact else 900
    for sid in ("information-inventory", "sequential-thinking"):
        tip = load_skill_assist(sid, explicit=False)
        if tip:
            parts.append(f"### {sid}\n" + _clip(tip, lim))
    if allow_other_tools:
        parts.append(
            "有工具时：需要可先 `think`，再搜集/验证，最后动手；不要对用户朗读草稿。"
        )
    return "\n\n".join(parts)


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
    seen: set[str] = set()
    items: list[dict] = []
    for key, sid in mapping.items():
        fp = _skill_path(sid)
        seen.add(sid)
        items.append({"id": sid, "role": key, "loaded": bool(fp), "source": "juno"})
    for entry in cc_skill_entries():
        sid = entry.get("id") or ""
        if not sid or sid in seen:
            continue
        seen.add(sid)
        items.append({
            "id": sid,
            "role": "cc",
            "loaded": bool(_skill_path(sid)),
            "source": "cc-skills",
            "intents": entry.get("intents") or [],
        })
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
        {"id": "brain_chain", "label": "Work chain", "active": on(HQ / "knowledge" / "cursor-brain-chain.md")},
        {"id": "workflow", "label": "工作流", "active": on(HQ / "knowledge" / "juno-workflow.md")},
        {"id": "thinking", "label": "思考", "active": on(HQ / "knowledge" / "juno-thinking-design.md")},
        {"id": "cursor_tools", "label": "读工具", "active": on(HQ / "knowledge" / "cursor-read-tools.md")},
        {"id": "cursor_agent", "label": "Agent协议", "active": on(HQ / "knowledge" / "cursor-agent-full.md")},
        {"id": "daily", "label": "今日日志", "active": on(daily / f"{today}.md")},
        {"id": "tools_hb", "label": "TOOLS/HB", "active": on(HQ / "TOOLS.md") or on(HQ / "HEARTBEAT.md")},
        {"id": "index", "label": "索引", "active": bool(idx.get("chunks")), "detail": str(idx.get("chunks") or 0)},
        {"id": "ide_ctx", "label": "IDE", "active": ide_on},
        {"id": "mcp", "label": "MCP", "active": mcp_on},
        {"id": "skill", "label": "Skill", "active": SKILLS_DIR.exists() and any(SKILLS_DIR.glob("*/SKILL.md"))},
        {"id": "plan", "label": "Plan块", "active": bool(_load_inject_block(HQ / "knowledge" / "juno-capabilities.md", "full-plan"))},
    ]
