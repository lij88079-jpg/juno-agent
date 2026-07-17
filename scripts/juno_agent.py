#!/usr/bin/env python3
"""Juno Agent loop — structured events for premium chat UI."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Generator

import juno_brain
import juno_index
import juno_orchestrator
import juno_tools

HQ = Path(__file__).resolve().parent.parent
TOOL_CALL_RE = re.compile(
    r"```(?:tool|json)\s*\n(\{[\s\S]*?\})\s*```",
    re.I,
)


def build_agent_system_prompt(*, chat_mode: str = "agent", plan_mode: bool = False, ask_mode: bool = False) -> str:
    ui_mode = juno_brain.resolve_ui_mode(chat_mode=chat_mode, plan_mode=plan_mode, ask_mode=ask_mode, agent_mode=True)
    tool_lines = "\n".join(
        f"- **{t['name']}**({', '.join(t['args'].keys())}): {t['desc']}"
        for t in juno_tools.TOOL_DEFS
    )
    roots = juno_tools.format_tool_roots_block()
    mode_note = ""
    if plan_mode:
        mode_note = "\n\nPlan：只规划，可用 read/search/grep/index；不 write/shell/git。"
    elif ask_mode:
        mode_note = "\n\nAsk：只读，不 write/shell/git。"
    fc_note = ""
    if juno_brain.supports_native_tools():
        fc_note = "\n\n云端模型已启用 function calling，直接调工具，勿用 ```tool``` 块。"
    return (
        juno_brain.build_system_prompt(mode="agent", ui_mode=ui_mode)
        + "\n\n"
        + roots
        + mode_note
        + fc_note
        + "\n\n## 可用工具\n"
        f"{tool_lines}\n\n"
        "### 本地模型调用格式（一轮一个 tool 或最终答案）\n"
        '```tool\n{"name":"read_file","args":{"path":"scripts/juno_brain.py","offset":1,"limit":80}}\n```'
        "\n\n## Work chain (Agent mode · flat interleaved timeline)\n"
        "每轮干活必须有自己的分析与计划，禁止碰到问题就无脑调工具。\n"
        "可见形态是一条时间线：Thinking ↔ Read/Grepped/Ran/Edited 穿插。\n"
        "1) 先调用 think：用 2～5 句写清「题意 / 成功标准 / 本轮计划」\n"
        "2) 再按计划 search/read/grep/write/shell；换方向或踩坑时再 think 一句\n"
        "3) 够答就终答。简单寒暄可不调工具，但有活绝不能没有先 think\n"
        "路径/行号必须来自工具结果。"
    )


def _build_api_messages(
    messages: list[dict],
    user_message: str,
    extra_system: list[str] | None = None,
    *,
    chat_mode: str = "agent",
    plan_mode: bool = False,
    ask_mode: bool = False,
    context_paths: list[dict] | None = None,
    session_title: str = "",
) -> list[dict]:
    import juno_skills

    ui_mode = juno_brain.resolve_ui_mode(chat_mode=chat_mode, plan_mode=plan_mode, ask_mode=ask_mode, agent_mode=True)
    prior = juno_brain.dialog_before_current(messages, user_message)
    intent = juno_orchestrator.classify_intent(user_message, prior or messages)
    compact = juno_brain.is_small_local_model()
    base_prompt = build_agent_system_prompt(chat_mode=chat_mode, plan_mode=plan_mode, ask_mode=ask_mode)

    # Same turn analysis + deliberation seal as Chat
    turn_ctx = juno_brain.build_turn_context(
        user_message,
        messages,
        agent_mode=True,
        ui_mode=ui_mode,
        session_title=session_title,
    )
    if turn_ctx:
        base_prompt = base_prompt + "\n\n" + turn_ctx

    skill_block = juno_skills.build_skill_inject(
        intent,
        user_message,
        compact=compact,
    )
    if skill_block:
        base_prompt = base_prompt + "\n\n" + skill_block

    # Match Chat deliberate: inventory + sequential when situational
    if juno_brain.needs_deliberation(user_message, prior):
        delib = juno_skills.format_deliberation_skills(
            allow_other_tools=True,
            compact=compact,
        )
        if delib:
            base_prompt = base_prompt + "\n\n" + delib
        if juno_brain.supports_native_tools():
            base_prompt += "\n云端已启用 function calling：先调 think，再调其它工具。"

    api_msgs = [{"role": "system", "content": base_prompt}]
    api_msgs.extend(
        juno_orchestrator.build_orchestrator_messages(
            user_message,
            context_paths=context_paths,
            plan_mode=plan_mode,
            recent_messages=messages,
            session_title=session_title,
        )
    )
    for block in extra_system or []:
        if block:
            api_msgs.append({"role": "system", "content": block})
    for m in messages:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            api_msgs.append({"role": m["role"], "content": m["content"]})
    return api_msgs


def _think_first_block(call: dict | None, *, force: bool, think_done: bool) -> dict | None:
    """Same Chat discipline: refuse other tools until at least one think on deliberate turns."""
    if not force or think_done or not call:
        return None
    if call.get("name") == "think":
        return None
    return {
        "ok": False,
        "error": "本轮需先用 think 完成信息盘点/分步想（与 Chat 同款），再调其它工具或终答。",
        "hint": "先调用 think：事实/约束/未知/成功标准 + 覆盖检查。",
    }


def parse_tool_call(text: str) -> dict | None:
    m = TOOL_CALL_RE.search(text or "")
    if not m:
        return None
    try:
        obj = json.loads(m.group(1))
        if obj.get("name"):
            return {"name": str(obj["name"]), "args": obj.get("args") or {}, "id": ""}
    except json.JSONDecodeError:
        return None
    return None


def parse_native_tool_call(step: dict) -> dict | None:
    for tc in step.get("tool_calls") or []:
        name = tc.get("name") or ""
        if not name:
            continue
        try:
            args = json.loads(tc.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        return {"name": name, "args": args, "id": tc.get("id") or ""}
    return None


def _rail_label(name: str, args: dict) -> str:
    """Cursor IDE style: Read file.py L1-80 / Grepped `pat` / …"""

    def _short_path(raw: str) -> str:
        p = str(raw or "").replace("\\", "/").rstrip("/")
        if not p or p in {".", "./"}:
            return "."
        parts = [x for x in p.split("/") if x]
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
        return parts[-1] if parts else "file"

    def _line_span(args: dict) -> str:
        try:
            off = int(args.get("offset") or 1)
        except (TypeError, ValueError):
            off = 1
        try:
            lim = int(args.get("limit") or 0)
        except (TypeError, ValueError):
            lim = 0
        if lim > 0:
            end = off + lim - 1
            return f" L{off}-{end}"
        if off > 1:
            return f" L{off}+"
        return ""

    if name == "read_file":
        return f"Read {_short_path(args.get('path') or '')}{_line_span(args)}"
    if name == "search_index":
        q = (args.get("query") or "").strip()[:40]
        return f"Searched `{q}`" if q else "Searched codebase"
    if name == "grep":
        pat = (args.get("pattern") or args.get("query") or "").strip()[:48]
        return f"Grepped `{pat}`" if pat else "Grepped"
    if name == "glob":
        pat = (args.get("pattern") or args.get("glob") or "").strip()[:40]
        return f"Glob `{pat}`" if pat else "Glob"
    if name == "list_dir":
        return f"Listed {_short_path(args.get('path') or '.')}"
    if name == "find_project":
        q = (args.get("query") or args.get("name") or "").strip()[:40]
        return f"Find project `{q}`" if q else "List projects"
    if name == "write_file":
        return f"Wrote {_short_path(args.get('path') or '')}"
    if name == "str_replace":
        return f"Edited {_short_path(args.get('path') or '')}"
    if name == "web_fetch":
        raw = (args.get("url") or "").strip()
        host = ""
        try:
            from urllib.parse import urlparse

            host = (urlparse(raw).netloc or "").removeprefix("www.")
        except Exception:
            host = ""
        return f"Fetched {host}" if host else "Fetched page"
    if name == "web_search":
        q = (args.get("query") or "").strip().replace("\n", " ")
        if len(q) > 28:
            q = q[:27] + "…"
        return f"Searched web `{q}`" if q else "Searched web"
    if name == "read_lints":
        return "Read lints"
    if name == "git":
        return f"Git {args.get('action', 'status')}"
    if name == "apply_patch":
        return f"Patched {_short_path(args.get('path') or '')}"
    if name == "delete_file":
        return f"Deleted {_short_path(args.get('path') or '')}"
    if name == "todo":
        return "Updated todos"
    if name == "task":
        k = args.get("kind") or "explore"
        return f"Subagent · {k}"
    if name == "mcp_call":
        return f"MCP · {args.get('server') or args.get('tool') or 'call'}"
    if name == "think":
        return "Thinking"
    if name == "run_shell":
        cmd = (args.get("command") or "").strip().replace("\n", " ")
        if len(cmd) > 72:
            cmd = cmd[:36] + "…" + cmd[-28:]
        return f"Ran {cmd}" if cmd else "Ran command"
    if name == "shell_job":
        jid = (args.get("job_id") or "")[:10]
        return f"Checked job {jid}" if jid else "Checked shell job"
    return name.replace("_", " ")


def _extract_paths_from_result(name: str, result: dict) -> list[str]:
    paths: list[str] = []
    if name == "read_file" and result.get("path"):
        paths.append(str(result["path"]))
    if name == "search_index":
        for h in result.get("hits") or []:
            if h.get("path"):
                paths.append(str(h["path"]))
    if name == "grep":
        for h in result.get("hits") or []:
            if h.get("path"):
                paths.append(str(h["path"]))
    if name == "list_dir" and result.get("path"):
        paths.append(str(result["path"]))
    if name == "find_project":
        proj = result.get("project") or {}
        if proj.get("resolved"):
            paths.append(str(proj["resolved"]))
        for p in result.get("projects") or []:
            if p.get("path"):
                paths.append(str(p["path"]))
    if name in ("write_file", "str_replace", "apply_patch") and result.get("path"):
        paths.append(str(result["path"]))
    if name == "glob":
        for m in result.get("matches") or []:
            paths.append(str(m))
    return paths[:12]


def _clip_result(result: dict, max_len: int = 2400) -> dict:
    try:
        s = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"ok": result.get("ok"), "summary": str(result)[:max_len]}
    if len(s) <= max_len:
        return result
    out = dict(result)
    out["_truncated"] = True
    for key in ("content", "stdout", "stderr", "patch", "diff"):
        if key in out and isinstance(out[key], str) and len(out[key]) > 600:
            out[key] = out[key][:600] + "…"
    s2 = json.dumps(out, ensure_ascii=False)
    if len(s2) > max_len:
        return {"ok": result.get("ok"), "summary": s[:max_len] + "…", "truncated": True}
    return out


def _tool_followup(result: dict, step: int, intent: str) -> str:
    import juno_orchestrator

    body = "工具结果（JSON）：\n" + json.dumps(result, ensure_ascii=False, indent=2)
    if result.get("ok") is False:
        err = (result.get("error") or result.get("hint") or "").strip()
        if err:
            body += f"\n\n（工具失败了：{err[:300]}。自己判断下一步。）"
    elif result.get("search_empty"):
        body += (
            "\n\n【搜空换招】这次搜索是空的。按 hint/next_tools 换根或换关键词；"
            "先 find_project 或 list_dir Desktop，禁止同一 path+pattern 再打一遍。"
        )
    if result.get("verify_hint"):
        body += f"\n\n【改完自检】{result.get('verify_hint')}"
    last_ok = None if result.get("ok") is None else bool(result.get("ok"))
    if result.get("search_empty"):
        last_ok = False  # treat empty search as soft failure for ladder
    directive = juno_orchestrator.step_directive(intent, step, last_ok, last_result=result)
    if directive:
        body += f"\n\n{directive}"
    return body


def _append_tool_messages(
    api_msgs: list[dict],
    *,
    call: dict,
    reply: str,
    result: dict,
    step: int,
    intent: str,
    native: bool,
    reasoning_content: str = "",
) -> None:
    if native and call.get("id"):
        msg: dict = {
            "role": "assistant",
            "content": reply or None,
            "tool_calls": [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["args"], ensure_ascii=False),
                    },
                }
            ],
        }
        if juno_brain.model_uses_reasoning_content():
            msg["reasoning_content"] = reasoning_content
        api_msgs.append(msg)
        api_msgs.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(_clip_result(result), ensure_ascii=False),
            }
        )
    else:
        api_msgs.append({"role": "assistant", "content": reply})
        api_msgs.append({"role": "user", "content": _tool_followup(result, step, intent)})


def _agent_step_events(
    api_msgs: list[dict],
    user_message: str,
    *,
    use_native: bool,
):
    """Yields thinking/answer deltas, then {kind:'step', reply, call}.

    answer_delta tokens are only emitted when this step is a final reply (no tools).
    """
    if use_native:
        step: dict | None = None
        tools_pending = False
        for ev in juno_brain.chat_agent_step_stream(
            api_msgs, user_message=user_message, tools=juno_tools.tool_schemas()
        ):
            kind = ev.get("kind")
            if kind == "tools_pending":
                tools_pending = True
            elif kind == "reasoning_delta":
                if juno_brain.should_emit_reasoning_to_ui(user_message):
                    text = juno_brain.sanitize_reasoning_chunk(ev.get("text") or "")
                    if text:
                        yield {"type": "thinking_delta", "text": text, "kind": "reasoning"}
            elif kind == "delta":
                # Upstream already suppresses content after tools_pending
                text = ev.get("text") or ""
                if text and not tools_pending:
                    yield {"type": "answer_delta", "text": text}
            elif kind == "step":
                step = ev
        if not step:
            yield {"type": "step", "reply": "", "call": None, "reasoning_content": ""}
            return
        call = parse_native_tool_call(step)
        yield {
            "type": "step",
            "reply": step.get("content") or "",
            "call": call,
            "reasoning_content": step.get("reasoning_content") or "",
            "streamed_answer": not bool(call),
        }
        return

    step_text: list[str] = []
    for delta in juno_brain.chat_stream(api_msgs, user_message=user_message):
        step_text.append(delta)
        # Non-native: may include tool markup — don't stream live
    reply = "".join(step_text)
    yield {"type": "step", "reply": reply, "call": parse_tool_call(reply), "streamed_answer": False}


def _agent_step(api_msgs: list[dict], user_message: str, *, use_native: bool) -> tuple[str, dict | None, str]:
    reply, call, reasoning = "", None, ""
    for ev in _agent_step_events(api_msgs, user_message, use_native=use_native):
        if ev.get("type") == "step":
            reply = ev.get("reply") or ""
            call = ev.get("call")
            reasoning = ev.get("reasoning_content") or ""
    return reply, call, reasoning


def run_agent_stream_events(
    messages: list[dict],
    *,
    user_message: str,
    extra_system: list[str] | None = None,
    chat_mode: str = "agent",
    plan_mode: bool = False,
    ask_mode: bool = False,
    context_paths: list[dict] | None = None,
    session_title: str = "",
) -> Generator[dict[str, Any], None, None]:
    """Yield flat CoT events: Exploring timeline of Thinking ↔ tools (Agent mode style)."""
    import time as _time

    cfg = juno_tools.load_profile()
    max_steps = int((cfg.get("tools") or {}).get("maxSteps") or 10)
    prior = juno_brain.dialog_before_current(messages, user_message)
    intent = juno_orchestrator.classify_intent(user_message, prior)
    sprint = juno_orchestrator.is_action_sprint(user_message)
    if sprint:
        max_steps = min(max_steps, 16)
    use_native = juno_brain.supports_native_tools()
    trace: list[dict] = []
    recent_sigs: list[tuple[str, bool]] = []
    t0 = _time.monotonic()

    light = juno_orchestrator.is_light_turn(intent)
    should_tools = juno_orchestrator.should_use_tools(intent)
    saw_reasoning = False
    think_count = 0
    exploring_opened = False
    tools_since_think = 0

    def _open_exploring():
        nonlocal exploring_opened
        # Light turns (hi / who-are-you): answer directly — no Exploring theater
        if light or exploring_opened:
            return None
        exploring_opened = True
        return {
            "type": "plan",
            "id": "plan-main",
            "label": "Exploring",
            "state": "active",
            "started_ms": int(t0 * 1000),
        }

    # Show rail immediately — don't leave a blank Exploring while index/API stalls
    if should_tools and not light:
        open_ev = _open_exploring()
        if open_ev:
            yield open_ev
        yield {
            "type": "thinking",
            "id": "boot-0",
            "text": "定位项目并准备动手…" if sprint else "整理任务…",
            "phase": "start",
            "label": "Thinking",
            "state": "active",
        }

    # Quiet index hint only (never fake Searched rows on the rail)
    # Action sprints: skip hybrid embed path — TF-IDF only / project prefetch is enough
    if should_tools and not sprint:
        try:
            hits = juno_index.search(user_message, top_k=6)
            paths = [h.get("path") for h in hits if h.get("path")]
            if paths:
                hint = "索引预览（勿对用户复述路径清单）：\n" + "\n".join(f"- {p}" for p in paths[:6])
                extra_system = list(extra_system or []) + [hint]
        except Exception:
            pass
    if sprint:
        try:
            pref = juno_orchestrator.prefetch_project_mentions(user_message)
            if pref:
                extra_system = list(extra_system or []) + [pref]
        except Exception:
            pass

    api_msgs = _build_api_messages(
        messages,
        user_message,
        extra_system,
        chat_mode=chat_mode,
        plan_mode=plan_mode,
        ask_mode=ask_mode,
        context_paths=context_paths,
        session_title=session_title,
    )
    # Heavy inject stack only when not in a run/fix sprint
    if not sprint:
        try:
            auto_turn = (HQ / "knowledge" / "juno-auto-turn.md").read_text(encoding="utf-8")
            if "<!-- INJECT:auto-turn -->" in auto_turn:
                block = auto_turn.split("<!-- INJECT:auto-turn -->", 1)[1].split("<!-- END:auto-turn -->", 1)[0].strip()
                if block and api_msgs and api_msgs[0].get("role") == "system":
                    api_msgs[0]["content"] = (api_msgs[0].get("content") or "") + "\n\n" + block
        except OSError:
            pass
        try:
            ph = (HQ / "knowledge" / "juno-problem-handling.md").read_text(encoding="utf-8")
            if "<!-- INJECT:problem-handling -->" in ph:
                block = ph.split("<!-- INJECT:problem-handling -->", 1)[1].split("<!-- END:problem-handling -->", 1)[0].strip()
                if block and api_msgs and api_msgs[0].get("role") == "system":
                    api_msgs[0]["content"] = (api_msgs[0].get("content") or "") + "\n\n" + block
        except OSError:
            pass
    try:
        fo = (HQ / "knowledge" / "juno-file-ops.md").read_text(encoding="utf-8")
        if "<!-- INJECT:file-ops -->" in fo:
            block = fo.split("<!-- INJECT:file-ops -->", 1)[1].split("<!-- END:file-ops -->", 1)[0].strip()
            if block and api_msgs and api_msgs[0].get("role") == "system":
                api_msgs[0]["content"] = (api_msgs[0].get("content") or "") + "\n\n" + block
    except OSError:
        pass

    if not sprint:
        try:
            po = (HQ / "knowledge" / "juno-port-ops.md").read_text(encoding="utf-8")
            if "<!-- INJECT:port-ops -->" in po:
                block = po.split("<!-- INJECT:port-ops -->", 1)[1].split("<!-- END:port-ops -->", 1)[0].strip()
                if block and api_msgs and api_msgs[0].get("role") == "system":
                    api_msgs[0]["content"] = (api_msgs[0].get("content") or "") + "\n\n" + block
        except OSError:
            pass
    elif api_msgs and api_msgs[0].get("role") == "system":
        api_msgs[0]["content"] = (
            (api_msgs[0].get("content") or "")
            + "\n\n## Action sprint\n"
            "User wants run/fix now. Prefer: resolve project path → list/read configs → "
            "run_shell (pnpm/npm/dev) or str_replace. Skip long analysis and web_search."
        )

    # Tools / lookup need a plan; light chat answers must NOT be forced into think theater
    # Action sprints skip forced think — go straight to tools
    force_lookup = (not sprint) and juno_orchestrator.needs_topic_lookup(user_message)
    force_plan = (not sprint) and bool(use_native) and (should_tools or force_lookup) and not light
    # Situation / design / multi-constraint: nudge think. Identity/hi never.
    force_any_think = (
        (not sprint)
        and bool(use_native)
        and not light
        and juno_brain.needs_deliberation(user_message, prior)
    )
    want_visual = juno_orchestrator.wants_visual(user_message)
    visual_retry = False
    lookup_retry = False
    pending_verify = False
    verify_nudge_sent = False
    edited_paths: list[str] = []

    def _emit_thinking_row(text: str, *, think_id: str, phase: str = "done"):
        body = (text or "").strip()
        if not body:
            return None
        return {
            "type": "thinking",
            "id": think_id,
            "text": body,
            "phase": phase,
            "label": "Thinking",
            "state": "done" if phase == "done" else "active",
        }

    for step in range(max_steps):
        reply, call, reasoning = "", None, ""
        step_reasoning_chunks: list[str] = []
        streamed_answer = False
        pending_answer: list[str] = []
        # Light identity/hi: buffer then polish — prevent prompt-echo loops on screen
        allow_live_answer = (not light) and bool(
            think_count >= 1 or saw_reasoning or not force_plan
        )
        for ev in _agent_step_events(api_msgs, user_message, use_native=use_native):
            if ev.get("type") == "thinking_delta" and ev.get("text"):
                saw_reasoning = True
                step_reasoning_chunks.append(ev["text"])
                open_ev = _open_exploring()
                if open_ev:
                    yield open_ev
                yield {
                    "type": "thinking",
                    "id": f"reason-{step}",
                    "text": ev["text"],
                    "phase": "delta",
                    "label": "Thinking",
                    "state": "active",
                }
                allow_live_answer = True
            elif ev.get("type") == "answer_delta" and ev.get("text"):
                if allow_live_answer:
                    streamed_answer = True
                    open_ev = _open_exploring()
                    if open_ev:
                        yield open_ev
                    yield {"type": "delta", "text": ev["text"]}
                else:
                    pending_answer.append(ev["text"])
            elif ev.get("type") == "step":
                reply = ev.get("reply") or ""
                call = ev.get("call")
                reasoning = ev.get("reasoning_content") or ""
                if ev.get("streamed_answer") and allow_live_answer:
                    streamed_answer = True

        if not call:
            need_think = (force_plan and think_count < 1 and not saw_reasoning) or (
                force_any_think and think_count < 1 and not saw_reasoning and not light
            )
            if need_think and use_native:
                pending_answer.clear()
                streamed_answer = False
                api_msgs.append({
                    "role": "system",
                    "content": (
                        "本轮还没有工作计划。请先调用 think："
                        "写清①用户要什么 ②成功标准 ③你准备怎么做（可跳过的步骤也说清），"
                        "然后再终答或调其它工具。禁止无分析直接答复杂题。"
                    ),
                })
                continue
            searched = any(
                (t.get("name") or "") in ("web_search", "search_index", "web_fetch", "grep", "read_file")
                for t in trace
            )
            if force_lookup and not lookup_retry and not searched and use_native:
                lookup_retry = True
                pending_answer.clear()
                streamed_answer = False
                api_msgs.append({
                    "role": "system",
                    "content": (
                        "这是不熟悉的专有名词/主题，还没查证。请先 web_search 或 search_index，"
                        "看清是什么再交付；要图的话查完必须出 mermaid/chart。"
                    ),
                })
                continue
            if (
                want_visual
                and not visual_retry
                and reply
                and "```mermaid" not in reply
                and "```chart" not in reply
                and "```chartjs" not in reply
            ):
                visual_retry = True
                pending_answer.clear()
                streamed_answer = False
                api_msgs.append({
                    "role": "assistant",
                    "content": reply,
                })
                api_msgs.append({
                    "role": "system",
                    "content": (
                        "用户明确要图，但你的答复里没有可渲染的 ```mermaid 或 ```chart。"
                        "请直接补一版完整图（可先一句说明假设），禁止只文字描述。"
                    ),
                })
                continue
            # Post-edit verify (Cursor-like): don't claim done without re-read
            if pending_verify and not verify_nudge_sent and use_native and not light:
                verify_nudge_sent = True
                pending_answer.clear()
                streamed_answer = False
                paths_hint = "、".join(edited_paths[-3:]) if edited_paths else "刚改的文件"
                api_msgs.append({
                    "role": "assistant",
                    "content": reply or "",
                })
                api_msgs.append({
                    "role": "system",
                    "content": (
                        f"你刚改过文件（{paths_hint}），还没做自检就准备终答了。"
                        "先 read_file 核对改动区间；代码文件再 read_lints；"
                        "用户要跑通再 run_shell。核对完再终答，禁止空口说「好了」。"
                    ),
                })
                continue
            elapsed_ms = int((_time.monotonic() - t0) * 1000)
            if exploring_opened or think_count or saw_reasoning:
                yield {
                    "type": "plan",
                    "id": "thought-summary",
                    "label": f"Thought for {max(1, elapsed_ms // 1000)}s",
                    "state": "done",
                    "elapsed_ms": elapsed_ms,
                }
            if exploring_opened:
                yield {"type": "plan", "id": "plan-main", "label": "Generating", "state": "done"}
            if pending_answer and not streamed_answer:
                for chunk in pending_answer:
                    yield {"type": "delta", "text": chunk}
                streamed_answer = True
            if reply and not streamed_answer:
                reply = juno_brain.polish_reply(reply, user_message)
                yield {"type": "delta", "text": reply}
            yield {"type": "done", "intent": intent, "trace": trace, "elapsed_ms": elapsed_ms, "light": light}
            return

        is_think = call["name"] == "think"
        open_ev = _open_exploring()
        if open_ev:
            yield open_ev

        # Mid-chain: after a burst of tools without rethink, soft nudge (not hard block)
        if (
            not is_think
            and think_count >= 1
            and tools_since_think >= 3
            and call["name"] in ("write_file", "str_replace", "run_shell", "apply_patch")
        ):
            api_msgs.append({
                "role": "system",
                "content": (
                    "你已连续读/搜几步还没再分析。动手改/跑之前先 think 一两句："
                    "确认依据是否够、风险是什么、下一步具体动哪。"
                ),
            })
            tools_since_think = 0  # only nudge once per burst

        label = _rail_label(call["name"], call["args"])
        tool_id = f"tool-{step}-{call['name']}"
        tool_t0 = _time.monotonic()

        if call["name"] == "task":
            yield {
                "type": "subagent",
                "id": tool_id + "-sub",
                "phase": "start",
                "label": f"Subagent · {(call['args'].get('kind') or 'explore')}",
                "state": "active",
                "kind": call["args"].get("kind") or "explore",
            }

        if is_think:
            # Show as Thinking row on the flat timeline (not a fake tool spam)
            thought_preview = str((call.get("args") or {}).get("thought") or "")[:80]
            yield {
                "type": "thinking",
                "id": tool_id,
                "text": "",
                "phase": "start",
                "label": "Thinking",
                "state": "active",
                "preview": thought_preview,
            }
        else:
            yield {
                "type": "tool",
                "id": tool_id,
                "phase": "start",
                "name": call["name"],
                "args": call["args"],
                "label": label,
                "state": "active",
            }

        blocked = _think_first_block(
            call,
            force=force_plan and not saw_reasoning,
            think_done=think_count >= 1 or saw_reasoning,
        )
        # Normalize explore signatures so path A/B vs A\B don't bypass the guard
        sig_args = dict(call["args"] or {})
        for pk in ("path", "cwd"):
            if pk in sig_args and isinstance(sig_args[pk], str):
                sig_args[pk] = sig_args[pk].replace("/", "\\").rstrip("\\").lower()
        sig = call["name"] + ":" + json.dumps(sig_args, sort_keys=True, ensure_ascii=False)
        if blocked:
            result = blocked
        else:
            same_ok = sum(1 for s, ok in recent_sigs if s == sig and ok)
            same_fail = sum(1 for s, ok in recent_sigs if s == sig and not ok)
            # Screenshot case: endless Listed run — block identical successful explores
            if same_ok >= 1 and call["name"] in (
                "list_dir",
                "glob",
                "grep",
                "search_index",
                "find_project",
                "read_file",
                "run_shell",
            ):
                result = {
                    "ok": False,
                    "error": "重复探索已拦截",
                    "loop_guard": (
                        "同一工具+参数已成功执行过：禁止再 list/glob/grep/shell 同一操作。"
                        "请用已有结果：进入更具体子目录、read 目标文件，或直接回答用户。"
                        "若路径曾被截断，用附件里的完整 source_path / find_project，不要猜半截路径。"
                    ),
                }
            elif same_fail >= 1:
                result = {
                    "ok": False,
                    "error": "重复失败已拦截",
                    "loop_guard": (
                        "同一工具+参数已连续失败：禁止再试；用 find_project / 完整绝对路径，"
                        "或根据已有结果直接回答。"
                    ),
                }
            else:
                result = juno_tools.run_tool(call["name"], call["args"])

        if is_think:
            if result.get("ok"):
                think_count += 1
                tools_since_think = 0
                thought = str(call["args"].get("thought") or "")
                row = _emit_thinking_row(thought, think_id=tool_id, phase="done")
                if row:
                    yield row
            else:
                yield {
                    "type": "thinking",
                    "id": tool_id,
                    "text": str(result.get("error") or "think failed"),
                    "phase": "done",
                    "label": "Thinking",
                    "state": "error",
                }
        elif result.get("ok"):
            tools_since_think += 1
            if call["name"] in ("str_replace", "apply_patch", "write_file"):
                pending_verify = True
                verify_nudge_sent = False
                p = str((call.get("args") or {}).get("path") or result.get("path") or "").strip()
                if p and p not in edited_paths:
                    edited_paths.append(p)
            elif call["name"] in ("read_file", "read_lints", "run_shell") and pending_verify:
                # Soft clear: any verify-style tool after edit counts
                pending_verify = False
                verify_nudge_sent = False

        recent_sigs.append((sig, bool(result.get("ok"))))
        if len(recent_sigs) > 8:
            recent_sigs.pop(0)

        if call["name"] == "task" and result.get("ok"):
            sub_trace = []
            for t in result.get("trace") or []:
                sub_trace.append(
                    {
                        "name": t.get("tool"),
                        "label": t.get("tool") or "tool",
                        "ok": bool((t.get("result") or {}).get("ok", True)),
                    }
                )
            yield {
                "type": "subagent",
                "id": tool_id + "-sub",
                "phase": "done",
                "label": f"Finished subagent · {(result.get('summary') or '')[:40]}",
                "state": "done",
                "kind": result.get("kind") or call["args"].get("kind") or "explore",
                "trace": sub_trace,
                "summary": result.get("summary") or "",
            }

        paths = _extract_paths_from_result(call["name"], result)
        clipped = _clip_result(result)
        trace.append(
            {
                "id": tool_id,
                "name": call["name"],
                "args": call["args"],
                "label": label if not is_think else "Thinking",
                "ok": bool(result.get("ok")),
                "result": clipped,
                "paths": paths,
            }
        )

        if not is_think:
            yield {
                "type": "tool",
                "id": tool_id,
                "phase": "done",
                "name": call["name"],
                "args": call["args"],
                "ok": bool(result.get("ok")),
                "label": label,
                "paths": paths,
                "result": clipped,
                "state": "done" if result.get("ok") else "error",
                "elapsed_ms": int((_time.monotonic() - tool_t0) * 1000),
            }

        _append_tool_messages(
            api_msgs,
            call=call,
            reply=reply,
            result=result,
            step=step,
            intent=intent,
            native=use_native,
            reasoning_content=reasoning,
        )

    # Max steps: one final no-tool synthesis from accumulated trace
    trace_blob = json.dumps(
        [{"tool": t.get("name"), "ok": t.get("ok"), "label": t.get("label"), "result": t.get("result")}
         for t in trace[-8:]],
        ensure_ascii=False,
    )[:5000]
    api_msgs.append(
        {
            "role": "user",
            "content": (
                "【步数上限】勿再调用任何工具。根据以下已执行的 tool 结果，用中文回答用户"
                "（结论→依据→下一步）；若工具均失败，诚实说明原因与建议。\n"
                f"```json\n{trace_blob}\n```"
            ),
        }
    )
    final_reply, final_call, _ = _agent_step(api_msgs, user_message, use_native=use_native)
    elapsed_ms = int((_time.monotonic() - t0) * 1000)
    yield {
        "type": "plan",
        "id": "thought-summary",
        "label": f"Thought for {max(1, elapsed_ms // 1000)}s",
        "state": "done",
        "elapsed_ms": elapsed_ms,
    }
    if final_call:
        yield {"type": "delta", "text": "（已达最大步数；部分工具未完成。请缩小范围或 @ 附加具体文件后重试。）"}
    elif final_reply:
        yield {"type": "delta", "text": juno_brain.polish_reply(final_reply, user_message)}
    else:
        yield {"type": "delta", "text": "（已达最大步数，请缩小问题范围重试。）"}
    yield {"type": "done", "intent": intent, "trace": trace, "elapsed_ms": elapsed_ms}


def run_agent_stream(
    messages: list[dict],
    *,
    user_message: str,
    extra_system: list[str] | None = None,
    plan_mode: bool = False,
    ask_mode: bool = False,
    session_title: str = "",
) -> Generator[str, None, None]:
    for ev in run_agent_stream_events(
        messages,
        user_message=user_message,
        extra_system=extra_system,
        plan_mode=plan_mode,
        ask_mode=ask_mode,
        session_title=session_title,
    ):
        if ev.get("type") == "delta" and ev.get("text"):
            yield ev["text"]


def run_agent_turn(
    messages: list[dict],
    *,
    user_message: str,
    extra_system: list[str] | None = None,
    chat_mode: str = "agent",
    plan_mode: bool = False,
    ask_mode: bool = False,
    context_paths: list[dict] | None = None,
    session_title: str = "",
    on_tool: Callable[[str, dict, dict], None] | None = None,
    on_delta: Callable[[str], None] | None = None,
) -> tuple[str, list[dict]]:
    cfg = juno_tools.load_profile()
    max_steps = int((cfg.get("tools") or {}).get("maxSteps") or 8)
    prior = juno_brain.dialog_before_current(messages, user_message)
    intent = juno_orchestrator.classify_intent(user_message, prior)
    use_native = juno_brain.supports_native_tools()
    api_msgs = _build_api_messages(
        messages,
        user_message,
        extra_system,
        chat_mode=chat_mode,
        plan_mode=plan_mode,
        ask_mode=ask_mode,
        context_paths=context_paths,
        session_title=session_title,
    )
    trace: list[dict] = []
    partial = ""
    force_deliberate = juno_brain.needs_deliberation(user_message, prior)
    think_done = False

    for step in range(max_steps):
        reply, call, reasoning = _agent_step(api_msgs, user_message, use_native=use_native)
        if not call:
            if force_deliberate and not think_done and use_native:
                api_msgs.append({
                    "role": "system",
                    "content": "还没 think。请先调用 think 做信息盘点，再终答或用其它工具。",
                })
                continue
            if on_delta and reply:
                on_delta(juno_brain.polish_reply(reply, user_message))
            return juno_brain.polish_reply(reply, user_message), trace

        blocked = _think_first_block(call, force=force_deliberate, think_done=think_done)
        if blocked:
            result = blocked
        else:
            result = juno_tools.run_tool(call["name"], call["args"])
            if call["name"] == "think" and result.get("ok"):
                think_done = True
        trace.append({"tool": call["name"], "args": call["args"], "result": result})
        if on_tool:
            on_tool(call["name"], call["args"], result)

        partial = reply
        _append_tool_messages(
            api_msgs,
            call=call,
            reply=reply,
            result=result,
            step=step,
            intent=intent,
            native=use_native,
            reasoning_content=reasoning,
        )

    msg = partial + "\n\n（编排层：已达最大步数，请缩小问题范围重试。）"
    if on_delta:
        on_delta(msg)
    return msg, trace


def _build_deliberate_chat_messages(
    messages: list[dict],
    user_message: str,
    *,
    session_title: str = "",
    extra_system: list[str] | None = None,
) -> list[dict]:
    """Chat prompt + sequential-thinking skill + forced deliberation (think-only tools)."""
    import juno_skills

    compact = juno_brain.is_small_local_model()
    prompt = juno_brain.build_system_prompt(mode="chat", ui_mode="chat")
    turn = juno_brain.build_turn_context(
        user_message,
        messages,
        agent_mode=False,
        ui_mode="chat",
        session_title=session_title,
    )
    if turn:
        prompt += "\n\n" + turn
    delib = juno_skills.format_deliberation_skills(allow_other_tools=False, compact=compact)
    if delib:
        prompt += "\n\n" + delib
    else:
        skill = juno_skills.build_skill_inject("chat", user_message, compact=compact)
        if skill:
            prompt += "\n\n" + skill
    if juno_brain.supports_native_tools():
        prompt += "\n云端已启用 function calling，请直接调用 think。"
    api_msgs = [{"role": "system", "content": prompt}]
    for block in extra_system or []:
        if block:
            api_msgs.append({"role": "system", "content": block})
    for m in messages:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            api_msgs.append({"role": m["role"], "content": m["content"]})
    return api_msgs


def run_deliberate_chat_turn(
    messages: list[dict],
    *,
    user_message: str,
    session_title: str = "",
    extra_system: list[str] | None = None,
    max_think_steps: int = 5,
) -> tuple[str, list[dict]]:
    """Chat-mode situational reasoning: only the `think` tool, then final answer."""
    use_native = juno_brain.supports_native_tools()
    api_msgs = _build_deliberate_chat_messages(
        messages,
        user_message,
        session_title=session_title,
        extra_system=extra_system,
    )
    think_tools = juno_tools.tool_schemas(only={"think"}) if use_native else None
    trace: list[dict] = []
    think_count = 0

    for step in range(max_think_steps):
        if use_native:
            step_ev: dict | None = None
            for ev in juno_brain.chat_agent_step_stream(
                api_msgs, user_message=user_message, tools=think_tools
            ):
                if ev.get("kind") == "step":
                    step_ev = ev
            if not step_ev:
                break
            reply = step_ev.get("content") or ""
            reasoning = step_ev.get("reasoning_content") or ""
            call = parse_native_tool_call(step_ev)
        else:
            reply, call, reasoning = _agent_step(api_msgs, user_message, use_native=False)

        if not call:
            return juno_brain.polish_reply(reply, user_message), trace

        # Chat deliberation: only allow think
        if call["name"] != "think":
            result = {
                "ok": False,
                "error": "本轮情景推理只允许 think 工具，请用 think 想完再作答。",
            }
        else:
            result = juno_tools.run_tool("think", call["args"])
            think_count += 1
        trace.append({"tool": call["name"], "args": call["args"], "result": result})
        _append_tool_messages(
            api_msgs,
            call=call,
            reply=reply,
            result=result,
            step=step,
            intent="chat",
            native=use_native,
            reasoning_content=reasoning,
        )
        # If model finished thinking chain, nudge once to answer
        if call["name"] == "think" and not result.get("next_thought_needed") and think_count >= 1:
            api_msgs.append(
                {
                    "role": "user",
                    "content": "思考已结束。请直接用中文给用户最终结论，不要再调用工具，不要朗读草稿。",
                }
            )

    # Last attempt: force answer without tools
    final, _usage = juno_brain.chat_complete(api_msgs, user_message=user_message)
    return juno_brain.polish_reply(final, user_message), trace


def run_deliberate_chat_stream_events(
    messages: list[dict],
    *,
    user_message: str,
    session_title: str = "",
    extra_system: list[str] | None = None,
    max_think_steps: int = 5,
) -> Generator[dict[str, Any], None, None]:
    """Stream deliberation: Thinking rows as think runs, then answer tokens live."""
    use_native = juno_brain.supports_native_tools()
    api_msgs = _build_deliberate_chat_messages(
        messages,
        user_message,
        session_title=session_title,
        extra_system=extra_system,
    )
    think_tools = juno_tools.tool_schemas(only={"think"}) if use_native else None
    trace: list[dict] = []
    think_count = 0
    t0 = __import__("time").monotonic()

    yield {
        "type": "plan",
        "id": "plan-thinking",
        "label": "Thinking",
        "state": "active",
        "started_ms": int(t0 * 1000),
    }

    for step in range(max_think_steps):
        if use_native:
            step_ev: dict | None = None
            tools_pending = False
            streamed = False
            for ev in juno_brain.chat_agent_step_stream(
                api_msgs, user_message=user_message, tools=think_tools
            ):
                kind = ev.get("kind")
                if kind == "tools_pending":
                    tools_pending = True
                elif kind == "reasoning_delta" and ev.get("text"):
                    yield {
                        "type": "thinking",
                        "id": f"reason-{step}",
                        "text": ev["text"],
                        "phase": "delta",
                        "label": "Thinking",
                        "state": "active",
                    }
                elif kind == "delta" and ev.get("text") and not tools_pending:
                    streamed = True
                    yield {"type": "delta", "text": ev["text"]}
                elif kind == "step":
                    step_ev = ev
            if not step_ev:
                break
            reply = step_ev.get("content") or ""
            reasoning = step_ev.get("reasoning_content") or ""
            call = parse_native_tool_call(step_ev)
        else:
            reply, call, reasoning = _agent_step(api_msgs, user_message, use_native=False)
            streamed = False

        if not call:
            elapsed_ms = int((__import__("time").monotonic() - t0) * 1000)
            yield {
                "type": "plan",
                "id": "thought-summary",
                "label": f"Thought for {max(1, elapsed_ms // 1000)}s",
                "state": "done",
                "elapsed_ms": elapsed_ms,
            }
            if reply and not streamed:
                yield {"type": "delta", "text": juno_brain.polish_reply(reply, user_message)}
            yield {
                "type": "done",
                "trace": trace,
                "content": juno_brain.polish_reply(reply, user_message) if reply else "",
            }
            return

        if call["name"] != "think":
            result = {
                "ok": False,
                "error": "本轮情景推理只允许 think 工具，请用 think 想完再作答。",
            }
        else:
            result = juno_tools.run_tool("think", call["args"])
            think_count += 1
            thought = str((call.get("args") or {}).get("thought") or "")
            if thought:
                yield {
                    "type": "thinking",
                    "id": f"think-{step}",
                    "text": thought,
                    "phase": "done",
                    "label": "Thinking",
                    "state": "done",
                }
            else:
                yield {
                    "type": "tool",
                    "id": f"think-{step}",
                    "phase": "done",
                    "name": "think",
                    "args": call.get("args"),
                    "label": "Thinking",
                    "state": "done",
                    "ok": True,
                }

        trace.append({"tool": call["name"], "args": call["args"], "result": result})
        _append_tool_messages(
            api_msgs,
            call=call,
            reply=reply,
            result=result,
            step=step,
            intent="chat",
            native=use_native,
            reasoning_content=reasoning,
        )
        if call["name"] == "think" and not result.get("next_thought_needed") and think_count >= 1:
            api_msgs.append(
                {
                    "role": "user",
                    "content": "思考已结束。请直接用中文给用户最终结论，不要再调用工具，不要朗读草稿。",
                }
            )

    # Last attempt: stream final without tools
    elapsed_ms = int((__import__("time").monotonic() - t0) * 1000)
    yield {
        "type": "plan",
        "id": "thought-summary",
        "label": f"Thought for {max(1, elapsed_ms // 1000)}s",
        "state": "done",
        "elapsed_ms": elapsed_ms,
    }
    full: list[str] = []
    for chunk in juno_brain.chat_stream(api_msgs, user_message=user_message):
        full.append(chunk)
        yield {"type": "delta", "text": chunk}
    reply = juno_brain.polish_reply("".join(full), user_message)
    yield {"type": "done", "trace": trace, "content": reply}
