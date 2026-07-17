#!/usr/bin/env python3
"""Juno Auto orchestration layer — intent routing + prefetch (Agent mode-lite)."""
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
    r"读.{0,4}文件|打开.{0,4}文件|看看.{0,6}(代码|目录|文件夹|路径|文件)|改.{0,4}(文件|一下)|"
    r"(桌面|下载|文档)(上|里|中)?的|打开看看|帮我(看|改|跑).{0,8}(文件|脚本|代码)|"
    r"read\s+file|\.(?:py|ts|tsx|js|jsx|md|json|html|css|vue|go|rs|txt|csv|docx|xlsx|pptx|pdf)\b",
    re.I,
)

SHELL_RE = re.compile(
    r"git\s|npm\s|pnpm\s|yarn\s|pytest|测试|运行|启动|前后端|报错|exit code|构建|build|commit|docker\s|uvicorn",
    re.I,
)

VISUAL_RE = re.compile(
    r"画(一张|个|一下)?|详解图|示意图|结构图|流程图|架构图|思维导图|对比图|可视化|mermaid|画图",
    re.I,
)

# Proper-noun / product-ish asks that need lookup before drawing or explaining
LOOKUP_RE = re.compile(
    r"(是什么|介绍|详解|系统|平台|产品|项目|功能|校园|官网|官网|怎么用)",
    re.I,
)


def wants_visual(user_message: str) -> bool:
    return bool(VISUAL_RE.search(user_message or ""))


def needs_topic_lookup(user_message: str) -> bool:
    """Ambiguous topic (e.g. 龙猫校园) — search before answering/drawing."""
    t = (user_message or "").strip()
    if not t or juno_tools.extract_paths_from_text(t):
        return False
    # Visual + named topic, or 「X 是什么」 style
    if wants_visual(t) and LOOKUP_RE.search(t):
        return True
    if juno_skills.RESEARCH_RE.search(t) and not juno_brain.is_technical_question(t):
        return True
    # 「画…某某」且不像纯代码路径
    if wants_visual(t) and not re.search(r"\.(py|ts|js|html|md|json)\b|仓库|代码|函数", t, re.I):
        return True
    return False


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
    # Meta: no fake Exploring — answer like a person
    if (
        juno_brain.is_mode_question(t)
        or juno_brain.is_model_identity_question(t)
        or juno_brain.is_self_identity_question(t)
        or juno_brain.is_creator_question(t)
        or juno_brain.is_juno_internals_question(t)
    ):
        return "meta"
    explicit = juno_skills.detect_explicit_skill(t)
    if explicit == "agent-memory":
        return "memory"
    if explicit == "agent-research":
        return "research"
    if explicit == "agent-writing":
        return "writing"
    if explicit in ("agent-coding", "my-core-agent"):
        pass  # fall through to heuristics
    if juno_brain.is_hostile_stance(t):
        return "hostile"
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
    # Diagram / unknown topic → research (search then deliver), not coding because of brand words
    if needs_topic_lookup(t) or (wants_visual(t) and not FILE_RE.search(t)):
        return "research"
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


def is_light_turn(intent: str) -> bool:
    """No tool gather / no fake Exploring rail."""
    return intent in ("meta", "casual", "frustrated", "hostile", "writing", "general")


def prefetch_project_mentions(user_message: str) -> str:
    """If user names a registered project, inject its root early (Cursor workspace-lite)."""
    text = (user_message or "").strip()
    if not text:
        return ""
    # Try whole message, then tokens / known aliases appearing in text
    hit = juno_tools.resolve_project_alias(text)
    if not hit:
        for proj in juno_tools.load_projects():
            keys = [proj.get("id") or "", proj.get("label") or ""] + list(proj.get("aliases") or [])
            for k in keys:
                k = str(k).strip()
                if len(k) >= 2 and k.lower() in text.lower():
                    hit = proj if proj.get("exists") else juno_tools.resolve_project_alias(k)
                    if hit:
                        break
            if hit:
                break
    if not hit or not hit.get("exists"):
        return ""
    juno_tools.trust_user_path(hit["resolved"])
    listing = juno_tools.tool_list_dir(hit["resolved"], max_entries=40)
    return (
        f"## 项目定位（通讯录命中）\n"
        f"- **{hit.get('label')}** · `{hit['resolved']}`\n"
        f"- 别名：{', '.join(hit.get('aliases') or [])}\n"
        f"- 后续 glob/grep/read 请用此路径，不要只在 Juno 总部搜。\n"
        f"```json\n{json.dumps(listing, ensure_ascii=False, indent=2)[:3500]}\n```"
    )


def prefetch_paths(user_message: str) -> str:
    """Auto-probe paths in user message (Cursor Read-lite)."""
    paths = juno_tools.extract_paths_from_text(user_message)
    if not paths:
        return ""
    lines = ["## 路径预读结果"]
    for p in paths:
        result = juno_tools.probe_path(p)
        lines.append(f"\n### `{p}`\n```json\n{json.dumps(result, ensure_ascii=False, indent=2)[:3500]}\n```")
    return "\n".join(lines)


def prefetch_index(user_message: str, *, top_k: int = 10) -> str:
    """Orchestrator runs retrieval before the model (like @codebase)."""
    intent = classify_intent(user_message)
    if intent in ("casual", "frustrated", "hostile", "writing"):
        return ""
    if not should_use_tools(intent):
        return ""
    hits = juno_index.search(user_message, top_k=top_k)
    if not hits:
        return ""
    lines = ["## 相关代码片段（自动检索）"]
    for i, h in enumerate(hits, 1):
        lines.append(
            f"\n### 预检索 {i} · `{h['path']}` (score {h['score']})\n```\n{h['text'][:1000]}\n```"
        )
    return "\n".join(lines)


def step_directive(
    intent: str,
    step: int,
    last_tool_ok: bool | None,
    last_result: dict | None = None,
) -> str:
    """Per-step nudge after tool execution."""
    last_result = last_result or {}
    if last_result.get("search_empty"):
        return (
            "【编排层】搜索为空：① find_project(项目名) ② list_dir Desktop/Documents "
            "③ 换 **/*name* / 放宽 grep ④ 仍空就问用户路径。"
            "禁止只在 Juno 总部重复同一 glob。"
        )
    if last_result.get("verify_hint") and last_tool_ok:
        return (
            "【编排层】刚改完文件：下一步 read_file 核对改动 → 代码文件 read_lints → "
            "需要跑通再 run_shell。核对前不要对用户说「好了」。"
        )
    if step == 0:
        if intent == "casual":
            return "【编排层】寒暄类：禁止调用工具，直接 1～2 句回复。"
        if intent == "hostile":
            return (
                "[Orchestrator] Abuse (Juno policy): follow the abuse-scene block — "
                "短骂冷处理、站队不背稿、禁止复读上一句、连骂无事则停；禁止道歉跪舔。"
            )
        if intent == "frustrated":
            return "【编排层】可处理的不满：禁止工具（除非用户明确要执行）；先认再改或追问卡点；禁止空道歉堆砌。"
        if intent == "writing":
            return "【编排层】写作类：先确认润色/翻译/新建；直接交付文案，不必 read 代码。"
        if intent == "research":
            return (
                "【编排层】调研：先 think 写清猜测→ search_index + web_search（未知实体必搜）→"
                "必要时 web_fetch → 结论。若用户要图，最终答复必须含 mermaid/chart，禁止只分析不交图。"
            )
        if intent == "memory":
            return "【编排层】记忆类：glob/read conversations → 提炼草稿 → 用户确认后 write_file MEMORY。"
        if intent == "design":
            return (
                "【编排层】设计/整套诉求：先 search/read 现有 brain/orchestrator/workflow；"
                "给架构级方案并 write 落实；只推荐一个方案。"
            )
        if intent == "technical":
            return (
                "【编排层】编码类：先 find_project/search_index/read_file；"
                "改代码用 str_replace；改完 read_file+read_lints 再终答。"
            )
        if intent == "shell":
            return "【编排层】验证类：先定位文件，再 run_shell（仅白名单命令）。"
        if intent == "file":
            return (
                "[Orchestrator] File ops (Agent-style): "
                "项目名 → find_project；桌面/下载/文档 → list_dir/glob → read_file；"
                "要改 → str_replace/write_file → 核对；要跑 → run_shell；"
                "办公件走 docx/xlsx/pdf skill。禁止编造未读内容。"
            )
        return "【编排层】一般问题：信息够就直接答，不够再 search_index。"
    if last_tool_ok is False:
        return (
            "【编排层】上次工具失败：读 error+hint 字段；换 find_project/glob/search_index/list_dir，"
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
        "hostile": "🔗 链路 ②③：无理攻击/诋毁 → 不道歉；站队或划界",
        "frustrated": "🔗 链路 ②③：可处理吐槽 → 先认再改，禁止工具与寒暄",
        "casual": "🔗 链路 ②③：纯寒暄 → 1～2 句",
        "writing": "🔗 链路 ③④：写作 skill → 交付文案",
        "research": f"🔗 链路 ⑤⑦ step={step}：本地检索 → web → 结论→要点→参考",
        "memory": f"🔗 链路 ⑧ step={step}：读对话 → 草稿 → 确认 → write MEMORY",
        "design": f"🔗 链路 ⑤⑥⑦ step={step}：先 read 现有实现 → 只推一个方案 → 四段式输出",
        "technical": f"🔗 链路 ⑤⑦ step={step}：search/read → str_replace 改代码 → 验证",
        "shell": f"🔗 链路 ⑤⑦ step={step}：定位文件 → 白名单 shell 验证",
        "file": f"🔗 链路 ⑤ file step={step}：list/glob → read →（改）str_replace/write →（跑）shell",
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
    """Factual prefetches + turn context only — no rulebook / chain / intent blocks."""
    import juno_context
    import juno_mcp_client

    msgs: list[dict] = []
    turn_ctx = juno_brain.build_turn_context(
        user_message,
        recent_messages,
        agent_mode=True,
        ui_mode="plan" if plan_mode else "agent",
        session_title=session_title,
    )
    if turn_ctx:
        msgs.append({"role": "system", "content": turn_ctx})
    ide_ctx = juno_context.format_for_prompt()
    if ide_ctx:
        msgs.append({"role": "system", "content": ide_ctx})
    cp = juno_tools.format_context_paths_inject(context_paths or [])
    if cp:
        msgs.append({"role": "system", "content": cp})
    path_pre = prefetch_paths(user_message)
    if path_pre:
        msgs.append({"role": "system", "content": path_pre})
    proj_pre = prefetch_project_mentions(user_message)
    if proj_pre:
        msgs.append({"role": "system", "content": proj_pre})
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
    return msgs
