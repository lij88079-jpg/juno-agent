#!/usr/bin/env python3
"""Juno capabilities loader — 听说读写 + compact/full prompt modes."""
from __future__ import annotations

from pathlib import Path

import juno_brain

HQ = Path(__file__).resolve().parent.parent
CAPS = HQ / "knowledge" / "juno-capabilities.md"


def _load_block(tag: str) -> str:
    if not CAPS.exists():
        return ""
    text = CAPS.read_text(encoding="utf-8")
    start, end = f"<!-- INJECT:{tag} -->", f"<!-- END:{tag} -->"
    if start not in text or end not in text:
        return ""
    return text.split(start, 1)[1].split(end, 1)[0].strip()


def load_capabilities(mode: str = "chat") -> str:
    tag = "full-agent" if mode == "agent" else "full-chat"
    return _load_block(tag) or _load_block("compact")


def load_compact_capabilities() -> str:
    return _load_block("compact")


def load_plan_capabilities() -> str:
    return _load_block("full-plan")


def capability_directive(user_message: str, *, agent_mode: bool, intent: str = "") -> str:
    """Per-turn 听说读写 hint."""
    parts: list[str] = []
    if juno_brain.is_user_frustrated(user_message):
        parts.append("【听】吐槽 · 【说】先认再改，禁止寒暄")
    elif juno_brain.is_casual_opening(user_message):
        parts.append("【听】寒暄 · 【说】1～2句即可")
    elif intent == "writing":
        parts.append("【听】写作需求 · 【说】交付文案 · 【写】润色/翻译/新建")
    elif intent == "research":
        if agent_mode:
            parts.append("【听】调研 · 【读】index→web_fetch · 【说】结论→要点→参考")
        else:
            parts.append("【听】调研 · 【读】MEMORY/检索 · 【说】不够建议 Agent")
    elif intent == "memory":
        parts.append("【听】记忆/学习 · 【读】conversations · 【写】草稿→确认→MEMORY")
    elif intent == "file":
        parts.append("【听】路径/读文件 · 【读】list_dir/read_file/grep/glob · 【说】引用 path:line，沙箱外如实说明")
    elif juno_brain.is_technical_question(user_message) or juno_brain.is_design_question(user_message):
        if agent_mode:
            parts.append("【听】编码/设计 · 【读】search/read · 【写】str_replace 或沙箱 write")
        else:
            parts.append("【听】技术/设计 · 【读】MEMORY/上传/检索 · 【说】无依据则建议 Agent")
    if "记住" in user_message or intent == "memory":
        parts.append("【写】用户要记忆 → 确认 MEMORY 沉淀")
    return " · ".join(parts)
