#!/usr/bin/env python3
"""Inbound MCP client — Juno Agent calls external MCP servers (stdio JSON-RPC)."""
from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
CONFIG = HQ / "config" / "mcp-inbound.json"
_lock = threading.Lock()
_sessions: dict[str, subprocess.Popen] = {}


def _load_config() -> dict:
    if CONFIG.exists():
        try:
            cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cfg = {"servers": []}
    else:
        cfg = {"servers": []}
    _merge_cursor_mcp(cfg)
    return cfg


def _merge_cursor_mcp(cfg: dict) -> None:
    """Merge servers from Cursor mcp.json only when importCursorMcp is a non-empty path."""
    raw = cfg.get("importCursorMcp")
    if raw is None or not str(raw).strip():
        return
    import_path = str(raw).strip()
    fp = Path(import_path).expanduser()
    if not fp.exists():
        return
    try:
        cur = json.loads(fp.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    existing = {s.get("id") for s in cfg.get("servers") or []}
    for sid, spec in (cur.get("mcpServers") or {}).items():
        if sid in existing:
            continue
        cfg.setdefault("servers", []).append(
            {
                "id": sid,
                "label": sid.title(),
                "command": spec.get("command", ""),
                "args": spec.get("args") or [],
                "enabled": sid != "openclaw",
                "timeout": 120 if sid == "scrapling" else 90,
                "fromCursor": True,
            }
        )


def list_servers() -> list[dict]:
    cfg = _load_config()
    out = []
    for s in cfg.get("servers") or []:
        if not s.get("enabled", True):
            continue
        tools = list_server_tools(s["id"])
        out.append({"id": s["id"], "label": s.get("label") or s["id"], "tools": [t.get("name") for t in tools]})
    return out


def _server_cfg(server_id: str) -> dict | None:
    for s in _load_config().get("servers") or []:
        if s.get("id") == server_id and s.get("enabled", True):
            return s
    return None


def _rpc(proc: subprocess.Popen, method: str, params: dict | None = None, timeout: float = 60) -> dict:
    rid = str(uuid.uuid4())
    msg: dict = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        msg["params"] = params
    assert proc.stdin and proc.stdout
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    deadline = time.time() + timeout
    while time.time() < deadline:
        chunk = proc.stdout.readline()
        if not chunk:
            break
        try:
            resp = json.loads(chunk.strip())
            if resp.get("id") == rid:
                if "error" in resp:
                    raise RuntimeError(str(resp["error"]))
                return resp.get("result") or {}
        except json.JSONDecodeError:
            continue
    raise TimeoutError(f"MCP RPC timeout: {method}")


def _get_proc(server_id: str) -> subprocess.Popen:
    with _lock:
        if server_id in _sessions and _sessions[server_id].poll() is None:
            return _sessions[server_id]
        cfg = _server_cfg(server_id)
        if not cfg:
            raise KeyError(f"未知 MCP server: {server_id}")
        cmd = [cfg["command"]] + list(cfg.get("args") or [])
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cfg.get("cwd") or HQ),
        )
        _rpc(proc, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "juno", "version": "0.4.0"}})
        _sessions[server_id] = proc
        return proc


def list_server_tools(server_id: str) -> list[dict]:
    try:
        proc = _get_proc(server_id)
        result = _rpc(proc, "tools/list")
        return result.get("tools") or []
    except Exception:
        return []


def call_tool(server_id: str, tool_name: str, arguments: dict | None = None) -> dict:
    cfg = _server_cfg(server_id)
    if not cfg:
        return {"ok": False, "error": f"未知 MCP server: {server_id}"}
    try:
        proc = _get_proc(server_id)
        result = _rpc(
            proc,
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
            timeout=float(cfg.get("timeout") or 90),
        )
        parts = result.get("content") or []
        text = "\n".join(
            p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"
        )
        return {
            "ok": not result.get("isError"),
            "server": server_id,
            "tool": tool_name,
            "content": text[:12000],
            "raw": result,
        }
    except Exception as e:
        return {"ok": False, "server": server_id, "tool": tool_name, "error": str(e)}


def tool_mcp_call(server: str, tool: str, arguments: dict | None = None) -> dict:
    return call_tool(server, tool, arguments or {})


def format_mcp_for_prompt() -> str:
    """Lightweight MCP server list for system prompt (no subprocess spawn)."""
    cfg = _load_config()
    servers = [s for s in (cfg.get("servers") or []) if s.get("enabled", True)]
    if not servers:
        return ""
    lines = ["## MCP 入站（`mcp_call` 工具 · 已启用 server）"]
    for s in servers:
        sid = s.get("id") or "?"
        label = s.get("label") or sid
        lines.append(f"- `{sid}` — {label}")
    lines.append(
        '- 调用：`{"name":"mcp_call","args":{"server":"scrapling","tool":"工具名","arguments":{}}}`'
    )
    return "\n".join(lines)
