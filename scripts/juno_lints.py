#!/usr/bin/env python3
"""Lightweight lint bridge (py_compile / ruff when available)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import juno_tools


def read_lints(paths: list[str] | None = None, *, path: str = "") -> dict:
    raw = paths or ([path] if path else [])
    if not raw:
        return {"ok": False, "error": "paths required"}

    diagnostics: list[dict] = []
    for p in raw:
        fp = juno_tools._resolve_allowed(p)
        if not fp or not fp.is_file():
            diagnostics.append({"path": p, "line": 0, "message": "文件不可访问", "severity": "error"})
            continue
        suffix = fp.suffix.lower()
        if suffix == ".py":
            diagnostics.extend(_lint_python(fp))
        elif suffix in (".ts", ".tsx", ".js", ".jsx"):
            diagnostics.extend(_lint_eslint(fp))
        else:
            diagnostics.append({"path": str(fp), "line": 0, "message": "无 linter 规则", "severity": "info"})
    return {"ok": True, "diagnostics": diagnostics}


def _lint_python(fp: Path) -> list[dict]:
    out: list[dict] = []
    try:
        proc = subprocess.run(
            ["python", "-m", "py_compile", str(fp)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "syntax error").strip()
            out.append({"path": str(fp), "line": 0, "message": msg[:400], "severity": "error"})
    except Exception as e:
        out.append({"path": str(fp), "line": 0, "message": str(e), "severity": "error"})

    try:
        proc = subprocess.run(
            ["ruff", "check", str(fp), "--output-format", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if proc.stdout.strip().startswith("["):
            import json
            for item in json.loads(proc.stdout):
                out.append({
                    "path": str(fp),
                    "line": item.get("location", {}).get("row", 0),
                    "message": item.get("message", ""),
                    "severity": "warning",
                })
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return out


def _lint_eslint(fp: Path) -> list[dict]:
    out: list[dict] = []
    try:
        proc = subprocess.run(
            ["npx", "--yes", "eslint", str(fp), "-f", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if proc.stdout.strip().startswith("["):
            import json
            for file_result in json.loads(proc.stdout):
                for msg in file_result.get("messages") or []:
                    out.append({
                        "path": str(fp),
                        "line": msg.get("line", 0),
                        "message": msg.get("message", ""),
                        "severity": msg.get("severity", 1),
                    })
    except FileNotFoundError:
        out.append({"path": str(fp), "line": 0, "message": "eslint 不可用", "severity": "info"})
    except Exception as e:
        out.append({"path": str(fp), "line": 0, "message": str(e), "severity": "info"})
    return out
