#!/usr/bin/env python3
"""Cursor-style subagents — explore (readonly) and shell (command) workers."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import juno_brain
import juno_index
import juno_orchestrator
import juno_tools

EXPLORE_TOOLS = {"read_file", "grep", "glob", "list_dir", "search_index", "web_search", "web_fetch", "read_lints"}
SHELL_TOOLS = {"run_shell", "grep", "read_file", "git"}


def _subagent_system(kind: str, prompt: str) -> str:
    if kind == "shell":
        return (
            f"你是 Juno Shell 子代理。任务：{prompt}\n"
            "只用 run_shell/git/grep/read_file。一轮一个 tool。完成后用中文总结 stdout。"
        )
    return (
        f"你是 Juno Explorer 子代理。任务：{prompt}\n"
        "只用 search_index/glob/grep/read_file/list_dir。一轮一个 tool。完成后总结发现。"
    )


def _allowed_tools(kind: str) -> set[str]:
    return SHELL_TOOLS if kind == "shell" else EXPLORE_TOOLS


def run_subagent(kind: str, prompt: str, *, max_steps: int = 5) -> dict:
    """Run a single subagent synchronously."""
    kind = (kind or "explore").strip().lower()
    if kind not in ("explore", "shell"):
        kind = "explore"
    allowed = _allowed_tools(kind)
    api_msgs = [
        {"role": "system", "content": _subagent_system(kind, prompt)},
        {"role": "user", "content": prompt},
    ]
    trace: list[dict] = []
    use_native = juno_brain.supports_native_tools()
    schemas = [s for s in juno_tools.tool_schemas() if s["function"]["name"] in allowed]

    for step in range(max_steps):
        if use_native and schemas:
            step_result = juno_brain.chat_agent_step(api_msgs, user_message=prompt, tools=schemas)
            call = None
            for tc in step_result.get("tool_calls") or []:
                try:
                    args = json.loads(tc.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                call = {"name": tc["name"], "args": args, "id": tc.get("id") or ""}
                break
            reply = step_result.get("content") or ""
            reasoning = step_result.get("reasoning_content") or ""
        else:
            chunks: list[str] = []
            for d in juno_brain.chat_stream(api_msgs, user_message=prompt):
                chunks.append(d)
            reply = "".join(chunks)
            reasoning = ""
            import juno_agent
            call = juno_agent.parse_tool_call(reply)

        if not call or call["name"] not in allowed:
            return {"ok": True, "kind": kind, "summary": reply, "trace": trace, "steps": step + 1}

        result = juno_tools.run_tool(call["name"], call["args"])
        trace.append({"tool": call["name"], "args": call["args"], "result": result})

        if use_native and call.get("id"):
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
                msg["reasoning_content"] = reasoning
            api_msgs.append(msg)
            api_msgs.append(
                {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)}
            )
        else:
            api_msgs.append({"role": "assistant", "content": reply})
            api_msgs.append(
                {
                    "role": "user",
                    "content": "工具结果：\n" + json.dumps(result, ensure_ascii=False, indent=2),
                }
            )

    return {"ok": True, "kind": kind, "summary": "（子代理步数上限）", "trace": trace, "steps": max_steps}


def run_parallel_tasks(tasks: list[dict], *, max_workers: int = 2) -> list[dict]:
    """Run multiple subagent tasks in parallel. Each: {kind, prompt, id?}."""
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 4))) as pool:
        futs = {
            pool.submit(run_subagent, t.get("kind") or "explore", t.get("prompt") or ""): t
            for t in tasks[:4]
        }
        for fut in as_completed(futs):
            t = futs[fut]
            try:
                r = fut.result()
                r["task_id"] = t.get("id") or t.get("prompt", "")[:24]
                results.append(r)
            except Exception as e:
                results.append({"ok": False, "task_id": t.get("id"), "error": str(e)})
    return results


def tool_task(action: str, *, kind: str = "explore", prompt: str = "", tasks: list | None = None) -> dict:
    """Agent tool: spawn subagent(s). action=run|parallel."""
    cfg = juno_tools.load_profile()
    max_sub = int((cfg.get("tools") or {}).get("maxSubagents") or 2)
    action = (action or "run").strip().lower()

    if action == "parallel":
        items = tasks or []
        if not items:
            return {"ok": False, "error": "parallel 需要 tasks 数组 [{kind,prompt}]"}
        out = run_parallel_tasks(items, max_workers=max_sub)
        return {"ok": True, "results": out}

    if not prompt.strip():
        return {"ok": False, "error": "run 需要 prompt"}
    return run_subagent(kind, prompt)
