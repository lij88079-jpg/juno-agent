#!/usr/bin/env python3
"""Juno MCP server — expose memory + index to Cursor (stdio MCP)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HQ / "scripts"))

import juno_context  # noqa: E402
import juno_index  # noqa: E402

MEMORY = HQ / "MEMORY.md"
TOOLS = [
    {
        "name": "juno_search_memory",
        "description": "Search Juno indexed knowledge and repos",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "juno_read_memory",
        "description": "Read Juno long-term MEMORY.md",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "juno_ide_context",
        "description": "Get current IDE context saved to Juno",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _reply(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_call(name: str, arguments: dict) -> dict:
    if name == "juno_search_memory":
        q = arguments.get("query") or ""
        hits = juno_index.search(q, top_k=6)
        return {"content": [{"type": "text", "text": json.dumps(hits, ensure_ascii=False, indent=2)}]}
    if name == "juno_read_memory":
        text = MEMORY.read_text(encoding="utf-8") if MEMORY.exists() else ""
        return {"content": [{"type": "text", "text": text[:12000]}]}
    if name == "juno_ide_context":
        ctx = juno_context.format_for_prompt()
        return {"content": [{"type": "text", "text": ctx or "(empty)"}]}
    return {"content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = req.get("id")
        method = req.get("method")
        if method == "initialize":
            _reply({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "juno", "version": "0.4.0"}}})
        elif method == "tools/list":
            _reply({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = req.get("params") or {}
            result = handle_call(params.get("name", ""), params.get("arguments") or {})
            _reply({"jsonrpc": "2.0", "id": rid, "result": result})
        elif method == "ping":
            _reply({"jsonrpc": "2.0", "id": rid, "result": {}})


if __name__ == "__main__":
    main()
