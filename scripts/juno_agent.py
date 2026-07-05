#!/usr/bin/env python3
"""Juno Agent loop — structured events for premium chat UI."""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Generator

import juno_brain
import juno_index
import juno_orchestrator
import juno_tools

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
        mode_note = (
            "\n\n## Plan 模式（只规划不执行）\n"
            "- 可用 read/grep/glob/list_dir/search_index/web_search/read_lints/todo\n"
            "- **禁止** write_file/str_replace/apply_patch/delete_file/git/run_shell\n"
            "- 输出分步方案、风险、文件清单；用户确认后再切 Agent 执行"
        )
    elif ask_mode:
        mode_note = (
            "\n\n## Ask 只读模式\n"
            "- 可用 read/search/grep/glob/web_search/read_lints\n"
            "- 禁止 write/str_replace/git/shell"
        )
    fc_note = ""
    if juno_brain.supports_native_tools():
        fc_note = "\n\n### Native tools\n云端模型已启用 function calling — 直接调用工具，勿用 ```tool``` 块。"
    fc_note += (
        "\n\n### 路径与读文件（必读）\n"
        "- 优先用 **绝对路径** 或相对项目根（见上方可读范围）。\n"
        "- read 失败看 JSON 的 `hint` / `allowed_roots`，用 **glob** 或 **search_index** 定位，勿重复同一 path。\n"
        "- 同一操作失败 2 次 → 换策略或向用户说明，禁止死循环。\n"
        "\n### 启动 dev 服务（Windows）\n"
        "- `pnpm run dev` / `npm run start` / `electron` 是**长驻进程**：用 **run_shell + cwd** 直接启动，输出在 **Juno 内置终端**。\n"
        "- **禁止** `start cmd /k`（会弹出外部黑窗口）。例：`{\"command\":\"npm run start\",\"cwd\":\"D:\\\\项目路径\"}`\n"
        "- 启动后用 `curl` 或 `netstat` 验证端口，不要重复 glob/read。"
    )
    return (
        juno_brain.format_ui_mode_directive(ui_mode)
        + "\n\n"
        + juno_brain.build_system_prompt(mode="agent")
        + "\n\n"
        + roots
        + mode_note
        + fc_note
        + "\n\n## Agent 工具（Cursor 同款读文件能力）\n"
        "### 可用工具\n"
        f"{tool_lines}\n\n"
        "### 调用格式（本地模型 · 一轮一个 tool 或最终答案）\n"
        '```tool\n{"name":"read_file","args":{"path":"scripts/juno_brain.py","offset":1,"limit":80}}\n```\n'
        '```tool\n{"name":"grep","args":{"pattern":"load_chat_config","path":"scripts"}}\n```\n'
        '```tool\n{"name":"glob","args":{"pattern":"**/*.py","path":"."}}\n```'
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
    ui_mode = juno_brain.resolve_ui_mode(chat_mode=chat_mode, plan_mode=plan_mode, ask_mode=ask_mode, agent_mode=True)
    api_msgs = [{"role": "system", "content": build_agent_system_prompt(chat_mode=chat_mode, plan_mode=plan_mode, ask_mode=ask_mode)}]
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
    prior = juno_brain.dialog_before_current(messages, user_message)
    intent = juno_orchestrator.classify_intent(user_message, prior)
    api_msgs.append({"role": "system", "content": juno_brain.tone_guard_directive(user_message, intent)})
    for m in messages:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            api_msgs.append({"role": m["role"], "content": m["content"]})
    return api_msgs


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
    if name == "read_file":
        p = str(args.get("path") or "")
        short = p.replace("\\", "/").split("/")[-1] or p or "file"
        return f"读取 {short}"
    if name == "search_index":
        q = (args.get("query") or "").strip()[:36]
        return f"搜索{'「' + q + '」' if q else ''}"
    if name == "grep":
        return "搜索代码"
    if name == "glob":
        return "浏览文件"
    if name == "list_dir":
        return "浏览目录"
    if name == "write_file":
        p = str(args.get("path") or "")
        short = p.replace("\\", "/").split("/")[-1] or "file"
        return f"写入 {short}"
    if name == "str_replace":
        p = str(args.get("path") or "")
        short = p.replace("\\", "/").split("/")[-1] or "file"
        return f"编辑 {short}"
    if name == "web_fetch":
        return "抓取网页"
    if name == "web_search":
        return "联网搜索"
    if name == "read_lints":
        return "检查语法"
    if name == "git":
        return f"Git {args.get('action', 'status')}"
    if name == "apply_patch":
        p = str(args.get("path") or "")
        short = p.replace("\\", "/").split("/")[-1] or "file"
        return f"已编辑 {short}"
    if name == "delete_file":
        return "删除文件"
    if name == "todo":
        return "更新待办"
    if name == "task":
        k = args.get("kind") or "explore"
        return f"子任务 {k}"
    if name == "mcp_call":
        return f"MCP {args.get('tool') or 'call'}"
    if name == "run_shell":
        cmd = str(args.get("command") or "")[:32]
        return f"Ran {cmd}" if cmd else "Ran command"
    return name.replace("_", " ").title()


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
    nudge = juno_orchestrator.step_directive(intent, step + 1, result.get("ok"))
    chain = juno_orchestrator.build_brain_chain_hint(intent, step + 1)
    return (
        "工具结果（JSON）：\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
        + f"\n\n{nudge}\n{chain}"
    )


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
    """Yields thinking deltas, then {kind:'step', reply, call}."""
    if use_native:
        step: dict | None = None
        for ev in juno_brain.chat_agent_step_stream(
            api_msgs, user_message=user_message, tools=juno_tools.tool_schemas()
        ):
            if ev.get("kind") == "reasoning_delta":
                yield {"type": "thinking_delta", "text": ev.get("text") or "", "kind": "reasoning"}
            elif ev.get("kind") == "delta":
                continue
            elif ev.get("kind") == "step":
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
        }
        return

    step_text: list[str] = []
    for delta in juno_brain.chat_stream(api_msgs, user_message=user_message):
        step_text.append(delta)
        yield {"type": "thinking_delta", "text": delta}
    reply = "".join(step_text)
    yield {"type": "step", "reply": reply, "call": parse_tool_call(reply)}


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
    """Yield structured events: plan, prefetch, tool, delta, done, trace."""
    cfg = juno_tools.load_profile()
    max_steps = int((cfg.get("tools") or {}).get("maxSteps") or 8)
    prior = juno_brain.dialog_before_current(messages, user_message)
    intent = juno_orchestrator.classify_intent(user_message, prior)
    use_native = juno_brain.supports_native_tools()
    trace: list[dict] = []
    recent_sigs: list[tuple[str, bool]] = []

    yield {
        "type": "plan",
        "id": "plan-main",
        "label": "Planning next moves",
        "state": "active",
    }

    if juno_orchestrator.should_use_tools(intent):
        hits = juno_index.search(user_message, top_k=10)
        if hits:
            paths = [h.get("path") for h in hits if h.get("path")]
            yield {
                "type": "prefetch",
                "id": "prefetch",
                "label": "Exploring",
                "paths": paths[:8],
                "state": "done",
            }

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

    for step in range(max_steps):
        reply, call, reasoning = "", None, ""
        for ev in _agent_step_events(api_msgs, user_message, use_native=use_native):
            if ev.get("type") == "thinking_delta" and ev.get("text"):
                yield {"type": "thinking_delta", "text": ev["text"]}
            elif ev.get("type") == "step":
                reply = ev.get("reply") or ""
                call = ev.get("call")
                reasoning = ev.get("reasoning_content") or ""

        if not call:
            yield {"type": "plan", "id": "plan-main", "label": "Generating answer", "state": "done"}
            if reply:
                reply = juno_brain.polish_reply_if_snark(reply, user_message)
                yield {"type": "delta", "text": reply}
            yield {"type": "done", "intent": intent, "trace": trace}
            return

        label = _rail_label(call["name"], call["args"])
        tool_id = f"tool-{step}-{call['name']}"
        if call["name"] == "task":
            yield {
                "type": "subagent",
                "id": tool_id + "-sub",
                "phase": "start",
                "label": f"Subagent · {(call['args'].get('kind') or 'explore')}",
                "state": "active",
                "kind": call["args"].get("kind") or "explore",
            }
        yield {
            "type": "tool",
            "id": tool_id,
            "phase": "start",
            "name": call["name"],
            "args": call["args"],
            "label": label,
            "state": "active",
        }

        result = juno_tools.run_tool(call["name"], call["args"])
        sig = call["name"] + ":" + json.dumps(call["args"], sort_keys=True, ensure_ascii=False)
        if not result.get("ok"):
            same_fail = sum(1 for s, ok in recent_sigs if s == sig and not ok)
            if same_fail >= 1:
                result = dict(result)
                result["loop_guard"] = (
                    "同一工具+参数已连续失败：禁止再试；用 glob/search_index/list_dir 换路径，"
                    "或直接根据已有结果回答用户。"
                )
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
                "label": label,
                "ok": bool(result.get("ok")),
                "result": clipped,
                "paths": paths,
            }
        )

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
    if final_call:
        yield {"type": "delta", "text": "（已达最大步数；部分工具未完成。请缩小范围或 @ 附加具体文件后重试。）"}
    elif final_reply:
        yield {"type": "delta", "text": juno_brain.polish_reply_if_snark(final_reply, user_message)}
    else:
        yield {"type": "delta", "text": "（已达最大步数，请缩小问题范围重试。）"}
    yield {"type": "done", "intent": intent, "trace": trace}


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

    for step in range(max_steps):
        reply, call, reasoning = _agent_step(api_msgs, user_message, use_native=use_native)
        if not call:
            if on_delta and reply:
                on_delta(juno_brain.polish_reply_if_snark(reply, user_message))
            return juno_brain.polish_reply_if_snark(reply, user_message), trace

        result = juno_tools.run_tool(call["name"], call["args"])
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
