#!/usr/bin/env python3
"""Juno local server — chat window + training studio."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
UI_STUDIO = HQ / "training" / "studio.html"
UI_CHAT = HQ / "training" / "chat.html"
UI_CURSOR_CSS = HQ / "training" / "cursor-ui.css"
UI_CURSOR_LAYOUT_CSS = HQ / "training" / "cursor-layout.css"
UI_CURSOR_JS = HQ / "training" / "cursor-ui.js"
UI_CURSOR_DIFF_JS = HQ / "training" / "cursor-diff-editor.js"
UI_CURSOR_TERM_JS = HQ / "training" / "cursor-terminal.js"
UI_CURSOR_CMDK_JS = HQ / "training" / "cursor-cmdk.js"
TRAINING_FILE = HQ / "training" / "examples.jsonl"
MEMORY = HQ / "MEMORY.md"
USER = HQ / "USER.md"
STATE = HQ / "config" / "sync-state.json"
SYNC_SCRIPT = HQ / "scripts" / "sync_cursor_chats.py"
SYNC_PIPELINE = HQ / "scripts" / "juno_sync_pipeline.py"
PORT = 8765

sys.path.insert(0, str(HQ / "scripts"))
import juno_brain  # noqa: E402
import juno_index  # noqa: E402
import juno_agent  # noqa: E402
import juno_orchestrator  # noqa: E402
import juno_uploads  # noqa: E402
import juno_capabilities  # noqa: E402
import juno_skills  # noqa: E402
import juno_tools  # noqa: E402
import juno_context  # noqa: E402


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def write_text(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def serve_html(handler: BaseHTTPRequestHandler, fp: Path) -> None:
    if not fp.exists():
        handler._json(404, {"error": f"{fp.name} missing"})
        return
    body = fp.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def serve_static(handler: BaseHTTPRequestHandler, fp: Path, content_type: str) -> None:
    if not fp.exists():
        handler._json(404, {"error": f"{fp.name} missing"})
        return
    body = fp.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def list_conversations() -> list[dict]:
    items = []
    for folder in [HQ / "knowledge" / "conversations" / "auto", HQ / "knowledge" / "conversations"]:
        if not folder.exists():
            continue
        for f in sorted(folder.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.name == "README.md":
                continue
            items.append(
                {
                    "name": f.name,
                    "path": str(f.relative_to(HQ)).replace("\\", "/"),
                    "size": f.stat().st_size,
                    "mtime": f.stat().st_mtime,
                }
            )
    return items[:200]


def load_training() -> list[dict]:
    if not TRAINING_FILE.exists():
        return []
    rows = []
    for line in TRAINING_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def save_training(rows: list[dict]) -> None:
    TRAINING_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TRAINING_FILE.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_api_messages(
    session: dict,
    *,
    chat_mode: str | None = None,
    agent_mode: bool = False,
    ask_mode: bool = False,
    plan_mode: bool = False,
    context_paths: list[dict] | None = None,
) -> list[dict]:
    user_msg = juno_brain.last_user_message(session)
    prior = juno_brain.dialog_before_current(session.get("messages"), user_msg)
    intent = juno_orchestrator.classify_intent(user_msg, prior or session.get("messages"))
    compact = juno_brain.is_small_local_model()
    ui_mode = juno_brain.resolve_ui_mode(
        chat_mode=chat_mode, agent_mode=agent_mode, ask_mode=ask_mode, plan_mode=plan_mode
    )
    mode = "agent" if ui_mode != "chat" else "chat"
    prompt = juno_brain.format_ui_mode_directive(ui_mode) + "\n\n" + juno_brain.build_system_prompt(mode=mode)
    skill = juno_skills.build_skill_inject(intent, user_msg, compact=compact)
    hint = juno_brain.scene_directive(
        user_msg,
        agent_mode=agent_mode or ask_mode or plan_mode,
        ui_mode=ui_mode,
        recent_messages=session.get("messages"),
        session_title=session.get("title") or "",
    )
    cap = juno_capabilities.capability_directive(user_msg, agent_mode=agent_mode or ask_mode, intent=intent)
    chain = juno_orchestrator.build_brain_chain_hint(intent, 0)
    if skill:
        prompt = prompt + "\n\n" + skill
    if not agent_mode:
        orch = juno_orchestrator.load_orchestrator_inject()
        if orch and not compact:
            prompt = prompt + "\n\n" + orch
    if plan_mode:
        prompt = prompt + "\n\n## Plan 模式\n只规划不执行 write/str_replace/git/shell；输出分步方案。"
        plan_caps = juno_capabilities.load_plan_capabilities()
        if plan_caps:
            prompt = prompt + "\n\n" + plan_caps
    elif ask_mode:
        prompt = prompt + "\n\n## Ask 只读模式\n可用 read/search/grep/glob/web_search/read_lints；禁止 write/str_replace/git/shell。"
    if cap:
        prompt = prompt + "\n\n## 本轮听说读写\n" + cap
    if not compact:
        prompt = prompt + "\n\n" + chain
    ctx = juno_context.format_for_prompt()
    if ctx:
        prompt = prompt + "\n\n" + ctx
    cp = juno_tools.format_context_paths_inject(context_paths or [])
    if cp:
        prompt = prompt + "\n\n" + cp
    if agent_mode or ask_mode or plan_mode:
        import juno_mcp_client
        mcp = juno_mcp_client.format_mcp_for_prompt()
        if mcp:
            prompt = prompt + "\n\n" + mcp
    attach = juno_uploads.format_attachments_for_prompt(session)
    if attach:
        prompt = prompt + "\n\n" + attach
    if not agent_mode and intent in ("technical", "design", "research", "shell", "memory", "coding", "file"):
        path_pre = juno_orchestrator.prefetch_paths(user_msg)
        if path_pre:
            prompt = prompt + "\n\n" + path_pre
        ctx2 = juno_index.format_context(user_msg, top_k=10)
        if ctx2:
            prompt = prompt + "\n\n" + ctx2 + "\n\n（检索片段；Chat 模式勿假装已读全文件，可开 Agent/Ask。）"
    if hint:
        prompt = prompt + "\n\n" + hint
    prompt = prompt + "\n\n" + juno_brain.tone_guard_directive(user_msg, intent)
    msgs = [{"role": "system", "content": prompt}]
    for m in session.get("messages") or []:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            msgs.append({"role": m["role"], "content": m["content"]})
    return msgs


def load_sync_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def schedule_post_chat_sync(session_id: str) -> None:
    """Background: sync conversation + auto-learn (non-blocking)."""

    def _run() -> None:
        try:
            subprocess.run(
                [sys.executable, str(SYNC_PIPELINE), session_id],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
                check=False,
            )
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, code: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _sse_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def _sse(self, event: str, data: dict) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _handle_chat_send(self, data: dict) -> None:
        sid = data.get("session_id")
        message = (data.get("message") or "").strip()
        stream = bool(data.get("stream", True))
        regenerate = bool(data.get("regenerate"))
        chat_mode_raw = (data.get("chat_mode") or "").strip().lower()
        if chat_mode_raw in ("chat", "agent", "plan", "ask"):
            chat_mode = chat_mode_raw
            agent_mode = chat_mode != "chat"
            ask_mode = chat_mode == "ask"
            plan_mode = chat_mode == "plan"
        else:
            agent_mode = bool(data.get("agent_mode"))
            ask_mode = bool(data.get("ask_mode"))
            plan_mode = bool(data.get("plan_mode"))
            chat_mode = juno_brain.resolve_ui_mode(
                agent_mode=agent_mode, ask_mode=ask_mode, plan_mode=plan_mode
            )
        route_agent = chat_mode != "chat"
        if route_agent:
            agent_mode = True
        juno_tools.set_readonly(ask_mode)
        juno_tools.set_plan_mode(plan_mode)
        if sid:
            juno_tools.set_session_context(str(sid))

        if sid:
            session = juno_brain.load_session(sid)
        else:
            session = None
        if not session:
            if regenerate:
                self._json(404, {"error": "session not found"})
                return
            sid = juno_brain.new_session_id()
            now = datetime.now().isoformat(timespec="seconds")
            session = {"id": sid, "title": (message or "新对话")[:24], "created": now, "updated": now, "messages": []}

        session.setdefault("messages", [])
        msgs = session["messages"]
        context_paths = data.get("context_paths") or []
        if not isinstance(context_paths, list):
            context_paths = []

        if not message and not regenerate:
            has_attach = bool(session.get("attachments"))
            has_ctx = bool(context_paths)
            if not has_attach and not has_ctx:
                self._json(400, {"error": "message required"})
                return
            message = "请阅读我附加的文件/上下文并回答。"

        if regenerate:
            juno_brain.pop_last_assistant(session)
            message = juno_brain.last_user_message(session)
            if not message:
                self._json(400, {"error": "no user message to regenerate"})
                return
        elif not (msgs and msgs[-1].get("role") == "user" and msgs[-1].get("content") == message):
            msgs.append({"role": "user", "content": message, "time": datetime.now().isoformat(timespec="seconds")})
            if session.get("title") in (None, "", "新对话"):
                session["title"] = message[:32]

        api_messages = build_api_messages(
            session,
            chat_mode=chat_mode,
            agent_mode=agent_mode,
            ask_mode=ask_mode,
            plan_mode=plan_mode,
            context_paths=context_paths,
        )
        user_msg = message or juno_brain.last_user_message(session)
        dialog = session.get("messages") or []
        extra = [juno_uploads.format_attachments_for_prompt(session)]

        if agent_mode:
            if stream:
                self._sse_start()
                full = []
                tool_trace: list[dict] = []
                try:
                    self._sse("status", {"phase": "agent"})
                    for ev in juno_agent.run_agent_stream_events(
                        dialog,
                        user_message=user_msg,
                        extra_system=[x for x in extra if x],
                        chat_mode=chat_mode,
                        plan_mode=plan_mode,
                        ask_mode=ask_mode,
                        context_paths=context_paths,
                        session_title=session.get("title") or "",
                    ):
                        et = ev.get("type")
                        if et == "delta":
                            t = ev.get("text") or ""
                            full.append(t)
                            self._sse("delta", {"text": t})
                        elif et in ("chain", "plan", "prefetch", "tool", "thinking_delta", "subagent"):
                            if et == "tool" and ev.get("phase") == "done":
                                tool_trace.append(ev)
                            self._sse(et, ev)
                        elif et == "done":
                            if ev.get("trace"):
                                tool_trace = ev.get("trace") or tool_trace
                    reply = "".join(full)
                    reply = juno_brain.polish_reply_if_snark(reply, user_msg)
                    session["messages"].append({
                        "role": "assistant",
                        "content": reply,
                        "time": datetime.now().isoformat(timespec="seconds"),
                        "trace": tool_trace,
                        "mode": chat_mode,
                    })
                    session["updated"] = datetime.now().isoformat(timespec="seconds")
                    juno_brain.save_session(session)
                    schedule_post_chat_sync(sid)
                    self._sse("done", {"session_id": sid, "content": reply, "syncing": True, "agent": True, "ask": ask_mode, "plan": plan_mode, "chat_mode": chat_mode, "trace": tool_trace})
                except Exception as e:
                    self._sse("error", {"message": str(e)})
                return
            reply, trace = juno_agent.run_agent_turn(
                dialog,
                user_message=user_msg,
                extra_system=[x for x in extra if x],
                chat_mode=chat_mode,
                plan_mode=plan_mode,
                ask_mode=ask_mode,
                context_paths=context_paths,
                session_title=session.get("title") or "",
            )
            reply = juno_brain.polish_reply_if_snark(reply, user_msg)
            session["messages"].append({"role": "assistant", "content": reply, "time": datetime.now().isoformat(timespec="seconds")})
            session["updated"] = datetime.now().isoformat(timespec="seconds")
            juno_brain.save_session(session)
            schedule_post_chat_sync(sid)
            self._json(200, {"session_id": sid, "content": reply, "agent": True, "trace": trace, "syncing": True})
            return

        if stream:
            self._sse_start()
            full = []
            try:
                if chat_mode != "chat":
                    self._sse("plan", {"id": "plan-main", "label": "Planning next moves", "state": "active"})
                self._sse("status", {"phase": "thinking"})
                for chunk in juno_brain.chat_stream(api_messages, user_message=user_msg):
                    if not full and chat_mode != "chat":
                        self._sse("plan", {"label": "Generating answer", "state": "done"})
                        self._sse("status", {"phase": "streaming"})
                    elif not full and chat_mode == "chat":
                        self._sse("status", {"phase": "streaming"})
                    full.append(chunk)
                    self._sse("delta", {"text": chunk})
                reply = "".join(full)
                reply = juno_brain.polish_reply_if_snark(reply, user_msg)
                session["messages"].append({
                    "role": "assistant",
                    "content": reply,
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "mode": chat_mode,
                })
                session["updated"] = datetime.now().isoformat(timespec="seconds")
                juno_brain.save_session(session)
                schedule_post_chat_sync(sid)
                self._sse("done", {"session_id": sid, "content": reply, "syncing": True, "chat_mode": chat_mode})
            except Exception as e:
                self._sse("error", {"message": str(e)})
            return

        reply, usage = juno_brain.chat_complete(api_messages, user_message=user_msg)
        reply = juno_brain.polish_reply_if_snark(reply, user_msg)
        session["messages"].append({"role": "assistant", "content": reply, "time": datetime.now().isoformat(timespec="seconds")})
        session["updated"] = datetime.now().isoformat(timespec="seconds")
        juno_brain.save_session(session)
        schedule_post_chat_sync(sid)
        self._json(200, {"session_id": sid, "content": reply, "usage": usage, "syncing": True})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path

        if path in ("/", "/index.html", "/studio"):
            serve_html(self, UI_STUDIO)
            return
        if path in ("/chat", "/chat.html"):
            serve_html(self, UI_CHAT)
            return
        if path == "/cursor-ui.css":
            serve_static(self, UI_CURSOR_CSS, "text/css; charset=utf-8")
            return
        if path == "/cursor-layout.css":
            serve_static(self, UI_CURSOR_LAYOUT_CSS, "text/css; charset=utf-8")
            return
        if path == "/cursor-ui.js":
            serve_static(self, UI_CURSOR_JS, "application/javascript; charset=utf-8")
            return
        if path == "/cursor-diff-editor.js":
            serve_static(self, UI_CURSOR_DIFF_JS, "application/javascript; charset=utf-8")
            return
        if path == "/cursor-terminal.js":
            serve_static(self, UI_CURSOR_TERM_JS, "application/javascript; charset=utf-8")
            return
        if path == "/cursor-cmdk.js":
            serve_static(self, UI_CURSOR_CMDK_JS, "application/javascript; charset=utf-8")
            return

        if path == "/api/status":
            state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
            self._json(
                200,
                {
                    "hq": str(HQ),
                    "last_sync": state.get("last_sync"),
                    "conversations": len(list_conversations()),
                    "training_count": len(load_training()),
                    "chat": juno_brain.chat_status(),
                },
            )
            return

        if path == "/api/chat/status":
            st = juno_brain.chat_status()
            sync_st = load_sync_state()
            st["last_sync"] = sync_st.get("last_sync")
            st["last_juno_sync"] = sync_st.get("last_juno_sync")
            st["last_auto_learn"] = sync_st.get("last_auto_learn")
            st["index"] = juno_index.index_status()
            st["agent_enabled"] = True
            st["skills"] = juno_skills.list_skills()
            st["inject_layers"] = juno_skills.list_inject_layers()
            self._json(200, st)
            return

        if path == "/api/index/status":
            self._json(200, juno_index.index_status())
            return

        if path == "/api/context/status":
            self._json(200, juno_context.load_context())
            return

        if path == "/api/index/search":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = (qs.get("q") or [""])[0]
            try:
                top_k = int((qs.get("k") or qs.get("top_k") or ["10"])[0])
            except ValueError:
                top_k = 10
            self._json(200, {"query": q, "hits": juno_index.search(q, top_k=top_k)})
            return

        if path == "/api/chat/presets":
            presets = juno_brain.load_presets()
            items = [{"id": k, **v} for k, v in presets.items()]
            self._json(200, {"items": items})
            return

        if path == "/api/chat/sessions":
            self._json(200, {"items": juno_brain.list_sessions()})
            return

        if path == "/api/chat/session":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            sid = (qs.get("id") or [""])[0]
            session = juno_brain.load_session(sid)
            if not session:
                self._json(404, {"error": "session not found"})
                return
            self._json(200, session)
            return

        if path == "/api/chat/attachment":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            sid = (qs.get("session_id") or [""])[0]
            att_id = (qs.get("id") or [""])[0]
            if not sid or not att_id:
                self._json(400, {"error": "session_id and id required"})
                return
            self._json(200, juno_uploads.read_attachment(sid, att_id))
            return

        if path == "/api/tools/roots":
            self._json(200, {"roots": juno_tools.tool_roots_labeled()})
            return

        if path == "/api/todos":
            self._json(200, juno_tools.tool_todo("list"))
            return

        if path == "/api/tools/files":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = (qs.get("q") or [""])[0].strip().lower()
            limit = int((qs.get("limit") or ["80"])[0])
            items = juno_tools.list_browsable_files(q=q, limit=limit)
            self._json(200, {"items": items})
            return

        if path == "/api/tools/tree":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            base = (qs.get("path") or [""])[0]
            depth = int((qs.get("depth") or ["2"])[0])
            self._json(200, juno_tools.list_dir_tree(base, depth=depth))
            return

        if path == "/api/mention/sources":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            kind = (qs.get("kind") or ["files"])[0]
            q = (qs.get("q") or [""])[0].strip()
            limit = int((qs.get("limit") or ["50"])[0])
            items = juno_tools.list_mention_sources(kind=kind, q=q, limit=limit)
            self._json(200, {"items": items})
            return

        if path == "/api/mcp/servers":
            import juno_mcp_client
            self._json(200, {"servers": juno_mcp_client.list_servers()})
            return

        if path == "/api/session/edits":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            sid = (qs.get("session_id") or [""])[0]
            self._json(200, {"edits": juno_tools.list_session_edits(sid)})
            return

        if path == "/api/session/trace":
            import juno_agent_trace
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            sid = (qs.get("session_id") or [""])[0]
            self._json(200, {"traces": juno_agent_trace.list_traces(session_id=sid or None)})
            return

        if path == "/api/tools/diff-preview":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            sid = (qs.get("session_id") or [""])[0]
            fpath = (qs.get("path") or [""])[0]
            if not sid or not fpath:
                self._json(400, {"error": "session_id and path required"})
                return
            self._json(200, juno_tools.get_diff_preview(sid, fpath))
            return

        if path == "/api/terminal/job":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            job_id = (qs.get("id") or [""])[0].strip()
            offset = int((qs.get("offset") or ["0"])[0])
            self._json(200, juno_tools.get_shell_job(job_id, offset=offset))
            return

        if path == "/api/memory":
            self._json(200, {"content": read_text(MEMORY)})
            return

        if path == "/api/user":
            self._json(200, {"content": read_text(USER)})
            return

        if path == "/api/conversations":
            self._json(200, {"items": list_conversations()})
            return

        if path == "/api/training":
            self._json(200, {"items": load_training()})
            return

        if path == "/api/conversation":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            rel = (qs.get("path") or [""])[0]
            fp = (HQ / rel).resolve()
            if not str(fp).startswith(str(HQ.resolve())) or not fp.exists():
                self._json(404, {"error": "not found"})
                return
            self._json(200, {"content": read_text(fp)})
            return

        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        data = self._read_json()

        if path == "/api/context/open-files":
            result = juno_context.save_context(data)
            self._json(200, result)
            return

        if path == "/api/chat/config":
            if data.get("preset"):
                try:
                    st = juno_brain.apply_preset(str(data["preset"]))
                except KeyError as e:
                    self._json(400, {"error": str(e)})
                    return
                self._json(200, {"ok": True, "chat": st})
                return
            patch = {}
            if data.get("provider"):
                patch["provider"] = str(data["provider"]).strip()
            if "api_key" in data:
                patch["api_key"] = str(data.get("api_key") or "").strip()
            if data.get("model"):
                patch["model"] = str(data["model"]).strip()
            if data.get("api_base"):
                patch["api_base"] = str(data["api_base"]).strip()
            if patch:
                if patch.get("provider") == "ollama":
                    patch.setdefault("api_base", "http://127.0.0.1:11434")
                juno_brain.save_local_config(patch)
            self._json(200, {"ok": True, "chat": juno_brain.chat_status()})
            return

        if path == "/api/chat/new":
            sid = juno_brain.new_session_id()
            now = datetime.now().isoformat(timespec="seconds")
            session = {"id": sid, "title": "新对话", "created": now, "updated": now, "messages": []}
            juno_brain.save_session(session)
            self._json(200, session)
            return

        if path == "/api/chat/send":
            try:
                self._handle_chat_send(data)
            except Exception as e:
                import traceback
                traceback.print_exc()
                try:
                    self._json(500, {"error": str(e)})
                except Exception:
                    pass
            return

        if path == "/api/chat/delete":
            sid = str(data.get("session_id") or "").strip()
            if not sid:
                self._json(400, {"error": "session_id required"})
                return
            ok = juno_brain.delete_session(sid)
            juno_tools.clear_session_edits(sid)
            self._json(200 if ok else 404, {"ok": ok})
            return

        if path == "/api/session/edits/revert":
            sid = str(data.get("session_id") or "").strip()
            paths = data.get("paths")
            if not sid:
                self._json(400, {"error": "session_id required"})
                return
            self._json(200, juno_tools.revert_session_edits(sid, paths=paths))
            return

        if path == "/api/session/edits/keep":
            sid = str(data.get("session_id") or "").strip()
            if not sid:
                self._json(400, {"error": "session_id required"})
                return
            self._json(200, juno_tools.clear_session_edits(sid))
            return

        if path == "/api/session/edits/hunk":
            sid = str(data.get("session_id") or "").strip()
            fpath = str(data.get("path") or "").strip()
            hunk_id = str(data.get("hunk_id") or "").strip()
            action = str(data.get("action") or "").strip().lower()
            if not sid or not fpath or not hunk_id or action not in ("accept", "reject"):
                self._json(400, {"error": "session_id, path, hunk_id, action required"})
                return
            self._json(200, juno_tools.apply_hunk_edit(sid, fpath, hunk_id, action))
            return

        if path == "/api/chat/regenerate":
            sid = str(data.get("session_id") or "").strip()
            if not sid:
                self._json(400, {"error": "session_id required"})
                return
            session = juno_brain.load_session(sid)
            if not session:
                self._json(404, {"error": "session not found"})
                return
            juno_brain.pop_last_assistant(session)
            juno_brain.save_session(session)
            self._json(200, {"ok": True, "session": session})
            return

        if path == "/api/chat/upload":
            sid = str(data.get("session_id") or "").strip()
            filename = str(data.get("filename") or "upload.txt").strip()
            content = data.get("content")
            if not sid or content is None:
                self._json(400, {"error": "session_id and content required"})
                return
            session = juno_brain.load_session(sid)
            if not session:
                self._json(404, {"error": "session not found"})
                return
            raw = content if isinstance(content, str) else str(content)
            result = juno_uploads.save_upload(sid, filename, raw.encode("utf-8"))
            if not result.get("ok"):
                self._json(400, {"error": result.get("error") or "upload failed"})
                return
            juno_uploads.merge_attachment(session, result["attachment"])
            juno_brain.save_session(session)
            self._json(200, {"ok": True, "attachment": result["attachment"], "preview": result.get("preview")})
            return

        if path == "/api/chat/attach-path":
            sid = str(data.get("session_id") or "").strip()
            fpath = str(data.get("path") or "").strip()
            if not sid or not fpath:
                self._json(400, {"error": "session_id and path required"})
                return
            session = juno_brain.load_session(sid)
            if not session:
                self._json(404, {"error": "session not found"})
                return
            result = juno_uploads.attach_workspace_file(sid, fpath)
            if not result.get("ok"):
                self._json(400, {"error": result.get("error") or "attach failed"})
                return
            juno_uploads.merge_attachment(session, result["attachment"])
            juno_brain.save_session(session)
            self._json(200, {"ok": True, "attachment": result["attachment"], "preview": result.get("preview")})
            return

        if path == "/api/chat/resolve-drop":
            folder_name = str(data.get("folder_name") or "").strip()
            self._json(200, juno_uploads.resolve_drop_folder(folder_name))
            return

        if path == "/api/inline-edit":
            sid = str(data.get("session_id") or "").strip()
            fpath = str(data.get("path") or "").strip()
            instruction = str(data.get("instruction") or "").strip()
            selection = str(data.get("selection") or "")
            if not instruction:
                self._json(400, {"error": "instruction required"})
                return
            if sid:
                juno_tools.set_session_context(sid)
            result = juno_tools.tool_inline_edit(fpath, instruction, selection)
            self._json(200 if result.get("ok") else 400, result)
            return

        if path == "/api/index/rebuild":
            try:
                result = juno_index.build_index(force=True)
            except Exception as e:
                self._json(500, {"error": str(e)})
                return
            self._json(200, result)
            return

        if path == "/api/sync":
            force = bool(data.get("force"))
            cmd = [sys.executable, str(SYNC_PIPELINE), "--all"]
            if force:
                cmd = [sys.executable, str(HQ / "scripts" / "sync_juno_chats.py"), "--force"]
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            try:
                result = json.loads(proc.stdout or "{}")
            except json.JSONDecodeError:
                result = {"stdout": proc.stdout, "stderr": proc.stderr}
            # also cursor
            proc2 = subprocess.run(
                [sys.executable, str(SYNC_SCRIPT)] + (["--force"] if force else []),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            try:
                cursor_result = json.loads(proc2.stdout or "{}")
            except json.JSONDecodeError:
                cursor_result = {"stdout": proc2.stdout}
            result["cursor"] = cursor_result
            self._json(200, result)
            return

        if path == "/api/memory":
            write_text(MEMORY, data.get("content", ""))
            self._json(200, {"ok": True})
            return

        if path == "/api/user":
            write_text(USER, data.get("content", ""))
            self._json(200, {"ok": True})
            return

        if path == "/api/training/add":
            rows = load_training()
            rows.insert(
                0,
                {
                    "question": data.get("question", "").strip(),
                    "answer": data.get("answer", "").strip(),
                    "tags": data.get("tags", []),
                    "created": data.get("created"),
                },
            )
            save_training(rows)
            self._json(200, {"ok": True, "count": len(rows)})
            return

        if path == "/api/training/delete":
            idx = int(data.get("index", -1))
            rows = load_training()
            if 0 <= idx < len(rows):
                rows.pop(idx)
                save_training(rows)
            self._json(200, {"ok": True, "count": len(rows)})
            return

        self._json(404, {"error": "not found"})


def main() -> None:
    print(f"Juno Chat:    http://127.0.0.1:{PORT}/chat")
    print(f"Juno Studio:  http://127.0.0.1:{PORT}/studio")
    print(f"HQ: {HQ}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
