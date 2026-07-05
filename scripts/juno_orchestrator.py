#!/usr/bin/env python3
"""Juno Auto orchestration layer — intent routing + prefetch (Cursor Auto-lite)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import juno_brain
import juno_capabilities
import juno_index
import juno_skills
import juno_tools

HQ = Path(__file__).resolve().parent.parent
ORCH_DOC = HQ / "knowledge" / "auto-orchestration.md"

FILE_RE = re.compile(
    r"读.{0,4}文件|打开.{0,4}文件|看看.{0,6}(代码|目录|文件夹|路径)|read\s+file|\.(?:py|ts|tsx|js|jsx|md|json|html|css|vue|go|rs)\b",
    re.I,
)

SHELL_RE = re.compile(r"git\s|npm\s|pytest|测试|运行|报错|exit code|构建|build|commit", re.I)


def load_orchestrator_inject() -> str:
    if not ORCH_DOC.exists():
        return "## Auto 编排层\n分类意图 → 该用工具才用 → 一次一个 tool → 有依据再答。"
    text = ORCH_DOC.read_text(encoding="utf-8")
    start, end = "<!-- INJECT:orchestrator -->", "<!-- END:orchestrator -->"
    if start not in text or end not in text:
        return "## Auto 编排层\n分类意图 → 该用工具才用 → 一次一个 tool → 有依据再答。"
    block = text.split(start, 1)[1].split(end, 1)[0].strip()
    return block or "## Auto 编排层"


def classify_intent(user_message: str, recent_messages: list[dict] | None = None) -> str:
    t = (user_message or "").strip()
    if not t:
        return "general"
    explicit = juno_skills.detect_explicit_skill(t)
    if explicit == "agent-memory":
        return "memory"
    if explicit == "agent-research":
        return "research"
    if explicit == "agent-writing":
        return "writing"
    if explicit in ("agent-coding", "my-core-agent"):
        pass  # fall through to heuristics
    if juno_brain.is_user_frustrated(t) or juno_brain.is_skeptical_short_reply(t):
        return "frustrated"
    if juno_brain.is_holistic_scope_request(t):
        return "design"
    if juno_brain.is_continuation_turn(t) and recent_messages:
        if juno_brain.FEEDBACK_NEGATIVE_RE.search(t):
            return "frustrated"
        return "general"
    if juno_brain.is_casual_opening(t) and not recent_messages:
        return "casual"
    if juno_tools.extract_paths_from_text(t) or FILE_RE.search(t):
        return "file"
    if juno_skills.MEMORY_RE.search(t):
        return "memory"
    if juno_skills.WRITING_RE.search(t):
        return "writing"
    if juno_skills.RESEARCH_RE.search(t):
        return "research"
    if juno_brain.is_design_question(t):
        return "design"
    if SHELL_RE.search(t) and juno_brain.is_technical_question(t):
        return "shell"
    if juno_brain.is_technical_question(t):
        return "technical"
    return "general"


def should_use_tools(intent: str) -> bool:
    return intent in ("technical", "shell", "design", "research", "memory", "coding", "file")


def prefetch_paths(user_message: str) -> str:
    """Auto-probe paths in user message (Cursor Read-lite)."""
    paths = juno_tools.extract_paths_from_text(user_message)
    if not paths:
        return ""
    lines = ["## 编排层 · 路径预读（用户给了路径，必须基于以下 tool 结果回答）"]
    for p in paths:
        result = juno_tools.probe_path(p)
        lines.append(f"\n### `{p}`\n```json\n{json.dumps(result, ensure_ascii=False, indent=2)[:3500]}\n```")
    return "\n".join(lines)


def prefetch_index(user_message: str, *, top_k: int = 10) -> str:
    """Orchestrator runs retrieval before the model (like @codebase)."""
    intent = classify_intent(user_message)
    if intent in ("casual", "frustrated", "writing"):
        return ""
    if not should_use_tools(intent):
        return ""
    hits = juno_index.search(user_message, top_k=top_k)
    if not hits:
        return ""
    lines = ["## 编排层预检索（已自动 search_index，请优先使用，勿编造）"]
    for i, h in enumerate(hits, 1):
        lines.append(
            f"\n### 预检索 {i} · `{h['path']}` (score {h['score']})\n```\n{h['text'][:1000]}\n```"
        )
    return "\n".join(lines)


def step_directive(intent: str, step: int, last_tool_ok: bool | None) -> str:
    """Per-step nudge after tool execution."""
    if step == 0:
        if intent == "casual":
            return "【编排层】寒暄类：禁止调用工具，直接 1～2 句回复。"
        if intent == "frustrated":
            return "【编排层】不满/纠正类：禁止工具（除非用户明确要执行）；结合上文，先认再改或追问卡点。"
        if intent == "writing":
            return "【编排层】写作类：先确认润色/翻译/新建；直接交付文案，不必 read 代码。"
        if intent == "research":
            return "【编排层】调研：search_index → web_search → web_fetch → 结论→要点→参考。"
        if intent == "memory":
            return "【编排层】记忆类：glob/read conversations → 提炼草稿 → 用户确认后 write_file MEMORY。"
        if intent == "design":
            return (
                "【编排层】设计/整套诉求：先 search/read 现有 brain/orchestrator/workflow；"
                "给架构级方案并 write 落实；只推荐一个方案。"
            )
        if intent == "technical":
            return "【编排层】编码类：若预检索不够，请 read_file；改代码用 str_replace；仍缺再用 grep。"
        if intent == "shell":
            return "【编排层】验证类：先定位文件，再 run_shell（仅白名单命令）。"
        if intent == "file":
            return "【编排层】读文件：优先用预读结果；不够再 read_file/glob/grep；禁止编造文件内容。"
        return "【编排层】一般问题：信息够就直接答，不够再 search_index。"
    if last_tool_ok is False:
        return (
            "【编排层】上次工具失败：读 error+hint 字段；换 glob/search_index/list_dir，"
            "勿用相同 path 重试；仍失败就直说原因，禁止编造。"
        )
    if step >= 5:
        return "【编排层】已多轮查询：必须根据已有 tool 结果输出最终答案，禁止再调用工具。"
    if step >= 3:
        return "【编排层】信息应已足够：优先输出最终答案；仅缺关键一行时才再 1 个 tool。"
    return "【编排层】继续：信息够就输出最终答案（不要 tool 块）；不够再 1 个 tool。"


def build_brain_chain_hint(intent: str, step: int = 0) -> str:
    """Per-turn link in the 10-step chain (orchestrator → model)."""
    chain = {
        "frustrated": "🔗 链路 ②③：听懂吐槽 → 先认再改，禁止工具与寒暄",
        "casual": "🔗 链路 ②③：纯寒暄 → 1～2 句",
        "writing": "🔗 链路 ③④：写作 skill → 交付文案",
        "research": f"🔗 链路 ⑤⑦ step={step}：本地检索 → web → 结论→要点→参考",
        "memory": f"🔗 链路 ⑧ step={step}：读对话 → 草稿 → 确认 → write MEMORY",
        "design": f"🔗 链路 ⑤⑥⑦ step={step}：先 read 现有实现 → 只推一个方案 → 四段式输出",
        "technical": f"🔗 链路 ⑤⑦ step={step}：search/read → str_replace 改代码 → 验证",
        "shell": f"🔗 链路 ⑤⑦ step={step}：定位文件 → 白名单 shell 验证",
        "file": f"🔗 链路 ⑤ read step={step}：list_dir/read_file → grep 补充 → 引用 path:line",
        "general": f"🔗 链路 ③④ step={step}：chat skill · 信息够直答",
    }
    return chain.get(intent, chain["general"])


def build_orchestrator_messages(
    user_message: str,
    *,
    context_paths: list[dict] | None = None,
    plan_mode: bool = False,
    recent_messages: list[dict] | None = None,
    session_title: str = "",
) -> list[dict]:
    """System messages injected by orchestrator before agent loop."""
    import juno_context
    import juno_mcp_client

    intent = classify_intent(user_message, juno_brain.dialog_before_current(recent_messages, user_message))
    compact = juno_brain.is_small_local_model()
    msgs: list[dict] = [{"role": "system", "content": load_orchestrator_inject()}]
    skill = juno_skills.build_skill_inject(intent, user_message, compact=compact)
    if skill:
        msgs.append({"role": "system", "content": skill})
    msgs.append({"role": "system", "content": juno_brain.load_brain_chain_inject("agent")})
    msgs.append({"role": "system", "content": build_brain_chain_hint(intent, 0)})
    skill_name = juno_skills.skill_for_intent(intent)
    msgs.append(
        {
            "role": "system",
            "content": f"【编排层意图】intent=`{intent}` · skill=`{skill_name}`。"
            + (" 应走工具链。" if should_use_tools(intent) else " 本轮优先不用工具。"),
        }
    )
    ide_ctx = juno_context.format_for_prompt()
    if ide_ctx:
        msgs.append({"role": "system", "content": ide_ctx})
    cp = juno_tools.format_context_paths_inject(context_paths or [])
    if cp:
        msgs.append({"role": "system", "content": cp})
    path_pre = prefetch_paths(user_message)
    if path_pre:
        msgs.append({"role": "system", "content": path_pre})
    pre = prefetch_index(user_message)
    if pre:
        msgs.append({"role": "system", "content": pre})
    mcp = juno_mcp_client.format_mcp_for_prompt()
    if mcp:
        msgs.append({"role": "system", "content": mcp})
    if plan_mode:
        plan_caps = juno_capabilities.load_plan_capabilities()
        if plan_caps:
            msgs.append({"role": "system", "content": plan_caps})
    cap = juno_capabilities.capability_directive(user_message, agent_mode=True, intent=intent)
    if cap:
        msgs.append({"role": "system", "content": "## 本轮听说读写\n" + cap})
    hint = juno_brain.scene_directive(
        user_message,
        agent_mode=True,
        recent_messages=recent_messages,
        session_title=session_title,
    )
    if hint:
        msgs.append({"role": "system", "content": hint})
    msgs.append({"role": "system", "content": juno_brain.tone_guard_directive(user_message, intent)})
    return msgs
