#!/usr/bin/env python3
"""Juno brain — local Ollama or cloud OpenAI-compatible APIs."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Generator

HQ = Path(__file__).resolve().parent.parent
SOUL = HQ / "SOUL.md"
USER = HQ / "USER.md"
MEMORY = HQ / "MEMORY.md"
TRAINING = HQ / "training" / "examples.jsonl"
WORKFLOW = HQ / "knowledge" / "juno-workflow.md"
THINKING = HQ / "knowledge" / "juno-thinking-design.md"
BRAIN_CHAIN = HQ / "knowledge" / "cursor-brain-chain.md"
CAPABILITIES = HQ / "knowledge" / "juno-capabilities.md"
CHAT_CFG = HQ / "config" / "chat.json"
CHAT_LOCAL = HQ / "config" / "chat.local.json"
PROFILE = HQ / "config" / "agent-profile.json"
SESSIONS_DIR = HQ / "memory" / "chat-sessions"

DEFAULT_CFG = {
    "provider": "ollama",
    "api_base": "http://127.0.0.1:11434",
    "model": "qwen2.5:7b",
    "max_tokens": 4096,
    "temperature": 0.7,
}


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def load_chat_config() -> dict:
    cfg = dict(DEFAULT_CFG)
    if CHAT_CFG.exists():
        cfg.update(json.loads(CHAT_CFG.read_text(encoding="utf-8")))
    if CHAT_LOCAL.exists():
        cfg.update(json.loads(CHAT_LOCAL.read_text(encoding="utf-8")))
    return cfg


def load_presets() -> dict:
    raw = {}
    if CHAT_CFG.exists():
        raw = json.loads(CHAT_CFG.read_text(encoding="utf-8"))
    return raw.get("presets") or {}


def apply_preset(name: str) -> dict:
    presets = load_presets()
    if name not in presets:
        raise KeyError(f"unknown preset: {name}")
    patch = dict(presets[name])
    patch.pop("label", None)
    save_local_config(patch)
    return chat_status()


def is_ollama(cfg: dict) -> bool:
    return cfg.get("provider", "ollama") == "ollama"


def _load_dotenv_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def get_api_key(cfg: dict) -> str | None:
    raw = cfg.get("api_key")
    if raw and str(raw).strip() not in ("", "lm-studio", "your-key-here"):
        return str(raw).strip()
    env_file = cfg.get("env_file") or cfg.get("qiankun_env")
    if env_file:
        key = _load_dotenv_value(Path(str(env_file)), "DEEPSEEK_API_KEY")
        if key:
            return key
    for name in [cfg.get("api_key_env"), "DEEPSEEK_API_KEY", "OPENAI_API_KEY"]:
        if name and os.environ.get(name):
            return os.environ[name]
    return None


def save_local_config(patch: dict) -> None:
    current = {}
    if CHAT_LOCAL.exists():
        current = json.loads(CHAT_LOCAL.read_text(encoding="utf-8"))
    current.update(patch)
    CHAT_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    CHAT_LOCAL.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")


def _http_get_json(url: str, *, timeout: int = 5) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ollama_base(cfg: dict) -> str:
    return cfg.get("api_base", "http://127.0.0.1:11434").rstrip("/")


def check_ollama(cfg: dict | None = None) -> dict:
    cfg = cfg or load_chat_config()
    base = ollama_base(cfg)
    try:
        data = _http_get_json(f"{base}/api/tags", timeout=3)
        models = [m.get("name", "") for m in data.get("models") or [] if m.get("name")]
        return {"running": True, "models": models, "base": base}
    except Exception as e:
        return {"running": False, "models": [], "base": base, "error": str(e)}


def load_training_examples(limit: int = 6) -> list[dict]:
    if not TRAINING.exists():
        return []
    rows = []
    for line in TRAINING.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    # Skip low-quality auto-learn rows that teach bad habits
    clean = []
    for row in rows:
        ans = (row.get("answer") or "").strip()
        tags = row.get("tags") or []
        if "auto-learn" in tags:
            if re.search(r"\bBased on the context\b|please tell me|I'm Juno", ans, re.I):
                continue
            if len(re.findall(r"[a-zA-Z]", ans)) > len(ans) * 0.35:
                continue
        if SNARK_REPLY_RE.search(ans):
            continue
        clean.append(row)
    return clean[:limit]


def trim_messages_for_context(messages: list[dict], *, max_turns: int = 24) -> list[dict]:
    """Keep system prompt + recent turns; preserve assistant/tool_call chains."""
    if not messages:
        return messages
    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    if not rest:
        return system
    user_idx = [i for i, m in enumerate(rest) if m.get("role") == "user"]
    if len(user_idx) <= max_turns:
        return system + rest
    return system + rest[user_idx[-max_turns]:]


GREETING_CUES = (
    "hi", "hello", "hey", "在吗", "在不在", "你好", "嗨", "早上好", "晚上好",
    "下午好", "早安", "晚安", "哈喽", "yo",
)
GREETING_SUFFIX_OK = frozenset({"", "啊", "呀", "哦", "嗯", "!", "！", "~", "～"})
FRUSTRATION_RE = re.compile(
    r"蠢|笨|傻|垃圾|废物|没用|什么玩意|答非所问|胡说|瞎说|好烂|太差|不满意|"
    r"不行啊|坏了|错了|聊不下去|听不懂|没听懂|说人话|别装|敷衍|人机|"
    r"无语|服了|难评|离谱|真行|还笑|别笑|呵呵呵|哈\s*哈",
    re.I,
)
SKEPTICAL_SHORT = frozenset({
    "呵呵", "哈", "哈哈", "hhh", "hh", "6", "66", "666", "额", "呃", "哦", "噢",
    "嗯", "嗯嗯", "行吧", "算了", "随便", "无语", "服了", "真行", "厉害", "难评",
    "笑死", "绷", "离谱", "草", "啧", "呵", "嘿", "唉", "哎",
    "呵呵。", "呵呵！", "哈哈。", "哦。", "6。", "行。", "好吧",
})
TECH_RE = re.compile(
    r"代码|bug|报错|函数|文件|脚本|接口|api|配置|项目|实现|逻辑|索引|agent|"
    r"\.ts|\.py|\.html|仓库|git|ollama|juno|龙猫|补跑|部署",
    re.I,
)
DESIGN_RE = re.compile(
    r"设计|架构|怎么做|如何实现|方案|重构|优化|规划|步骤|流程|模块|"
    r"该怎么|帮我想|梳理|拆分|trade.?off|选型|提升|改进|优化一下",
    re.I,
)
CONTINUATION_RE = re.compile(
    r"继续|然后呢|然后|接着|刚才|上面|之前|那个|这个|再来|怎么样了|好了吗|"
    r"可以吗|弄好了|搞定|完成了吗|懂了吗|明白吗|还是",
    re.I,
)
SNARK_REPLY_RE = re.compile(
    r"你赢了|说吧[，,]?要干嘛|行[，,]?你赢了|随便你|爱咋咋|咋不上天|"
    r"斗嘴|油嘴滑舌|人机感|陪笑|哈哈哈.*赢|赢了你",
    re.I,
)
FEEDBACK_NEGATIVE_RE = re.compile(
    r"不对|不行|没用|不好|错了|还不是|没解决|没好|拖不上|开不了|用不了|"
    r"不好使|有问题|咋还不|怎么还|整体|只是个例|只是例子",
    re.I,
)
HOLISTIC_SCOPE_RE = re.compile(
    r"整套|整体|全面|通用|系统性|每个用户|所有用户|每条消息|每条|各种情况|"
    r"听懂.*意图|理解.*意图|真正.*意思|用户想|不是只修|不要只|别只针对|"
    r"不要只修|单点|打补丁|holistic|举一反三",
    re.I,
)
COMMAND_RE = re.compile(
    r"^(帮我|请|麻烦|启动|开始|改|加|删|跑|执行|修复|实现|部署|重启|打开|关闭|弄|做)",
    re.I,
)
TURN_TYPE_LABELS = {
    "holistic_scope": "要整套/系统性方案（非单点补丁）",
    "feedback": "对上一轮不满或短句评价",
    "continuation": "延续上一轮任务",
    "contextual_short": "短句，需接上文理解",
    "command": "要你执行/动手",
    "design": "要方案/设计/怎么实现",
    "technical": "具体技术问题",
    "question": "提问/求解释",
    "casual": "纯寒暄开场",
    "meta": "问模式/模型等元信息",
    "new_task": "新任务/新话题",
    "unknown": "待澄清",
}


def load_workflow_inject(mode: str = "chat") -> str:
    """Load injectable workflow block from knowledge/juno-workflow.md."""
    tag = "agent" if mode == "agent" else "chat"
    fallback = (
        "## 思考与工作流\n"
        "听懂意图 → 定类型 → 只答一件事 → 不确定就说不知道；禁止编造文件内容。"
    )
    if not WORKFLOW.exists():
        return fallback
    text = read_text(WORKFLOW)
    start = f"<!-- INJECT:{tag} -->"
    end = f"<!-- END:{tag} -->"
    if start not in text or end not in text:
        return fallback
    block = text.split(start, 1)[1].split(end, 1)[0].strip()
    return block or fallback


def load_thinking_inject(mode: str = "chat") -> str:
    tag = "agent" if mode == "agent" else "chat"
    fallback = "## 怎么思考\n先听懂目标 → 先结论 → 不确定就说不知道。"
    if not THINKING.exists():
        return fallback
    text = read_text(THINKING)
    start, end = f"<!-- INJECT:{tag} -->", f"<!-- END:{tag} -->"
    if start not in text or end not in text:
        return fallback
    block = text.split(start, 1)[1].split(end, 1)[0].strip()
    return block or fallback


def load_brain_chain_inject(mode: str = "chat") -> str:
    """Master inject: full brain + work chain (Cursor Auto parity)."""
    tag = "chain-agent" if mode == "agent" else "chain-chat"
    fallback = (
        "## 核心工作链\n"
        "听懂 → 定策略 → 有依据再答 → 先结论；Chat 不编造文件，Agent 先 tool。"
    )
    if not BRAIN_CHAIN.exists():
        return fallback
    text = read_text(BRAIN_CHAIN)
    start, end = f"<!-- INJECT:{tag} -->", f"<!-- END:{tag} -->"
    if start not in text or end not in text:
        return fallback
    block = text.split(start, 1)[1].split(end, 1)[0].strip()
    return block or fallback


def is_technical_question(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 4:
        return False
    return bool(TECH_RE.search(t))


def is_design_question(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 4:
        return False
    return bool(DESIGN_RE.search(t))


def is_continuation_turn(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if CONTINUATION_RE.search(t):
        return True
    if len(t) <= 24 and FEEDBACK_NEGATIVE_RE.search(t):
        return True
    return False


def dialog_before_current(messages: list[dict] | None, user_message: str) -> list[dict]:
    """Exclude the current user turn when summarizing prior context."""
    msgs = messages or []
    if not msgs:
        return []
    last = msgs[-1]
    if last.get("role") == "user" and (last.get("content") or "").strip() == (user_message or "").strip():
        return msgs[:-1]
    return msgs


def needs_context_first(user_message: str, recent_messages: list[dict] | None) -> bool:
    t = (user_message or "").strip()
    if not t:
        return False
    if is_skeptical_short_reply(t) or is_user_frustrated(t) or is_continuation_turn(t):
        return True
    if not recent_messages:
        return False
    if len(t) <= 24:
        return True
    return False


def is_holistic_scope_request(text: str) -> bool:
    t = (text or "").strip()
    return bool(t and HOLISTIC_SCOPE_RE.search(t))


def last_message_by_role(messages: list[dict] | None, role: str, *, max_len: int = 320) -> str:
    for m in reversed(messages or []):
        if m.get("role") == role:
            c = (m.get("content") or "").strip().replace("\n", " ")
            if c:
                return c[:max_len]
    return ""


def classify_turn_type(user_message: str, prior: list[dict] | None) -> str:
    t = (user_message or "").strip()
    prior = prior or []
    if not t:
        return "unknown"
    if is_holistic_scope_request(t):
        return "holistic_scope"
    if is_mode_question(t) or is_model_identity_question(t):
        return "meta"
    if is_casual_opening(t) and not prior:
        return "casual"
    if is_user_frustrated(t) or is_skeptical_short_reply(t):
        return "feedback"
    if is_continuation_turn(t):
        return "continuation"
    if FEEDBACK_NEGATIVE_RE.search(t) and prior:
        return "feedback"
    if COMMAND_RE.search(t) or re.search(r"帮我|给我|去做|赶紧", t):
        return "command"
    if is_design_question(t):
        return "design"
    if is_technical_question(t):
        return "technical"
    if "?" in t or re.search(r"吗[?？]?$|么[?？]?$|^什么|^怎么|^为何|^为什么|^哪", t):
        return "question"
    if prior and len(t) <= 30:
        return "contextual_short"
    return "new_task"


def infer_response_mode(turn_type: str, *, agent_mode: bool = False) -> str:
    modes = {
        "holistic_scope": "给系统级/架构级方案并落实改动；禁止只改一个词或一条 if",
        "feedback": "先承认可能没做好 → 追问具体卡点或立刻改正",
        "continuation": "接着上一轮做/说，禁止装失忆或开新话题",
        "contextual_short": "结合上文判断满意/不满/催进度，勿当全新寒暄",
        "command": "直接执行" if agent_mode else "说明步骤或请开 Agent 模式执行",
        "design": "目标→约束→推荐方案(一个)→下一步",
        "technical": "先结论后做法；Agent 必须先查再答",
        "question": "直接回答所问；不确定就说不知道",
        "casual": "1～2 句，不长篇自我介绍",
        "meta": "按 system 权威信息简短回答",
        "new_task": "聚焦本句新诉求，并保持与会话主题一致",
        "unknown": "礼貌请用户补充一句",
    }
    return modes.get(turn_type, modes["new_task"])


def infer_user_goal(
    user_message: str,
    recent_messages: list[dict] | None,
    *,
    turn_type: str = "",
    session_title: str = "",
) -> str:
    t = (user_message or "").strip()
    if not t:
        return "等待用户说明"
    tt = turn_type or classify_turn_type(t, recent_messages)
    if tt == "holistic_scope":
        return "要整套能力（尤其每轮听懂用户真实意图），不是单点修词/单条规则"
    if tt == "command":
        return "要看到结果：执行、启动、改好，不是空讲"
    if tt == "meta":
        return "确认当前模式/模型等元信息"
    if tt == "casual":
        return "寒暄开场，简短回应即可"
    if "只是个例" in t or "只是例子" in t or "举个例子" in t:
        return "用户在纠正范围：要整体能力/通用方案，不要只修单个词或单个案例"
    if tt in ("feedback", "contextual_short"):
        if recent_messages:
            return "对上一轮不满意或在评价刚才的表现，先承认再追问或继续改"
        title = (session_title or "").strip()
        if title and title not in ("新对话", ""):
            return f"短句需结合会话「{title[:24]}」理解；先承认可能没做好，再追问卡点"
        return "短句/语气词，需结合上文；先承认可能没做好，再追问具体卡点"
    if tt == "continuation":
        return "延续上一轮任务，接着做或接着解释，不要开新话题"
    if FEEDBACK_NEGATIVE_RE.search(t):
        return "指出仍有问题，针对具体卡点改进"
    if tt == "design" or is_design_question(t):
        return "要方案/设计/整体提升，给出可落地步骤"
    if tt == "technical" or is_technical_question(t):
        return "要解决具体技术问题，先结论后做法"
    if tt == "question":
        return "回答所问，简洁有据"
    if len(t) <= 20 and recent_messages:
        return "短句回应，必须结合上一轮理解，勿当全新话题"
    title = (session_title or "").strip()
    if title and title not in ("新对话", "") and not recent_messages:
        return f"新对话但主题可能是「{title[:24]}」，按此理解诉求"
    return "按本句诉求作答，并保持与会话上文一致"


def analyze_user_turn(
    user_message: str,
    recent_messages: list[dict] | None,
    *,
    session_title: str = "",
    agent_mode: bool = False,
) -> dict:
    """Structured per-turn intent — used on every user message."""
    prior = recent_messages or []
    t = (user_message or "").strip()
    turn_type = classify_turn_type(t, prior)
    last_asst = last_message_by_role(prior, "assistant")
    last_user = last_message_by_role(prior, "user")
    linked = ""
    if last_asst and turn_type in (
        "feedback", "continuation", "contextual_short", "holistic_scope",
    ):
        linked = f"上轮 Juno：{last_asst}"
    elif last_user and turn_type == "continuation":
        linked = f"上轮用户：{last_user}"
    title = (session_title or "").strip()
    if not linked and title and title not in ("", "新对话"):
        linked = f"会话主题：{title}"
    goal = infer_user_goal(t, prior, turn_type=turn_type, session_title=session_title)
    return {
        "turn_type": turn_type,
        "literal": t[:500],
        "linked_prior": linked,
        "goal": goal,
        "response_mode": infer_response_mode(turn_type, agent_mode=agent_mode),
    }


def format_turn_understanding(analysis: dict, *, compact: bool = False) -> str:
    tt = analysis.get("turn_type") or "new_task"
    label = TURN_TYPE_LABELS.get(tt, tt)
    if compact:
        block = (
            f"## 【听懂用户】{label}\n"
            f"目标：{analysis.get('goal', '')}\n"
            f"做法：{analysis.get('response_mode', '')}"
        )
        if analysis.get("linked_prior"):
            block += f"\n接：{analysis['linked_prior'][:180]}"
        return block
    lines = [
        "## 【听懂用户 · 每轮必读】",
        "接的是**用户此刻想达成的事**，不是最后一串字面。",
        "",
        f"- **字面**：{analysis.get('literal', '')[:240]}",
        f"- **回合类型**：{label}",
        f"- **用户目标**：{analysis.get('goal', '')}",
        f"- **该怎么回**：{analysis.get('response_mode', '')}",
    ]
    if analysis.get("linked_prior"):
        lines.append(f"- **接哪里**：{analysis['linked_prior']}")
    lines.extend([
        "",
        "**开口前三问**：① 延续上文还是新话题？② 要结果、解释还是改我行为？③ 下一步动手、说明还是追问？",
        "**禁止**：装失忆、答非所问、只修用户举的单个例子而忽略整体诉求。",
    ])
    return "\n".join(lines)


def build_understanding_directive(
    user_message: str,
    recent_messages: list[dict] | None,
    *,
    agent_mode: bool = False,
    session_title: str = "",
    compact: bool | None = None,
) -> str:
    """Universal per-turn intent layer — always injected."""
    if compact is None:
        compact = is_small_local_model()
    prior = recent_messages or []
    analysis = analyze_user_turn(
        user_message, prior, session_title=session_title, agent_mode=agent_mode,
    )
    block = format_turn_understanding(analysis, compact=compact)
    recent = summarize_recent_turns(prior)
    if recent and not compact:
        block += f"\n\n**最近对话摘要：**\n{recent}"
    return block


def tone_guard_directive(user_message: str, intent: str = "") -> str:
    """Last-inject tone guard — short/skeptical turns get the strict block."""
    t = (user_message or "").strip()
    strong = (
        intent == "frustrated"
        or is_user_frustrated(t)
        or is_skeptical_short_reply(t)
        or is_continuation_turn(t)
        or len(t) <= 20
    )
    if strong:
        return (
            "## 【语气底线 · 最高优先级】\n"
            "你是靠谱技术助手，**不是**斗嘴网友。\n"
            "**严禁**：「你赢了」「说吧要干嘛」「行吧你赢了」「随便」「怼回去」「阴阳怪气」「陪笑应付」。\n"
            "**短句/不满/呵呵等**：默认在评价上一轮 → 平实承认可能没做好 + 问具体哪不对或接着改。\n"
            "**示例**：「刚才可能没接住。是指哪一块？我继续改。」"
        )
    return (
        "## 【语气】\n"
        "专业、直接、不油嘴滑舌；用户不满时先认再改，禁止斗嘴。"
    )


def polish_reply_if_snark(text: str, user_message: str = "") -> str:
    """Replace snarky model output with a professional fallback."""
    t = (text or "").strip()
    if not t or not SNARK_REPLY_RE.search(t):
        return text
    if is_skeptical_short_reply(user_message) or is_user_frustrated(user_message):
        return "刚才可能没接住你的意思。你是指哪一块不对？我接着改。"
    return "刚才表述不合适。请说下具体想解决什么，我继续帮你。"


def is_skeptical_short_reply(text: str) -> bool:
    """Very short reply — tone depends on context, often pushback not laughter."""
    t = (text or "").strip()
    if not t or len(t) > 14:
        return False
    low = t.lower()
    if low in SKEPTICAL_SHORT or t in SKEPTICAL_SHORT:
        return True
    if re.fullmatch(r"[呵哈6额呃哦嗯\.。~～!！?？…\s]+", t):
        return True
    if re.fullmatch(r"(呵{2,}|哈{2,}|6{1,3})", low):
        return True
    return False


def summarize_recent_turns(messages: list[dict] | None, *, max_chars: int = 900) -> str:
    if not messages:
        return ""
    lines: list[str] = []
    for m in messages[-6:]:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        c = (m.get("content") or "").strip().replace("\n", " ")
        if not c:
            continue
        label = "用户" if role == "user" else "Juno"
        lines.append(f"- {label}：{c[:320]}")
    text = "\n".join(lines[-4:])
    return text[:max_chars] if text else ""


def is_user_frustrated(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if is_skeptical_short_reply(t):
        return True
    return bool(FRUSTRATION_RE.search(t))


def is_casual_opening(text: str) -> bool:
    """Pure greeting only — '你好蠢' / '呵呵' is NOT a greeting."""
    t = (text or "").strip().lower()
    if not t or len(t) > 24:
        return False
    if is_user_frustrated(t) or is_skeptical_short_reply(t):
        return False
    for c in GREETING_CUES:
        if t == c:
            return True
        for sep in (" ", "，", ",", "!", "！"):
            if t.startswith(c + sep):
                rest = t[len(c) + len(sep) :].strip(" ，,!！。~～…")
                if rest in GREETING_SUFFIX_OK:
                    return True
                return False
        if t.startswith(c):
            rest = t[len(c) :].strip(" ，,!！。~～…")
            if rest in GREETING_SUFFIX_OK:
                return True
            return False
    return False


def is_mode_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    return bool(
        re.search(
            r"什么模式|哪个模式|当前模式|现在.*模式|啥模式|mode\s*now|what\s+mode|which\s+mode",
            t,
        )
    )


def resolve_ui_mode(
    *,
    chat_mode: str | None = None,
    agent_mode: bool = False,
    ask_mode: bool = False,
    plan_mode: bool = False,
) -> str:
    m = (chat_mode or "").strip().lower()
    if m in ("chat", "agent", "plan", "ask"):
        return m
    if plan_mode:
        return "plan"
    if ask_mode:
        return "ask"
    if agent_mode:
        return "agent"
    return "chat"


def format_ui_mode_directive(mode: str) -> str:
    meta = {
        "chat": ("○ Chat", "纯对话，无工具读写。禁止声称处于 Plan/Agent/Ask。"),
        "agent": ("∞ Agent", "可读写、跑 shell、改文件。"),
        "plan": ("◈ Plan", "只规划不执行 write/shell/git。"),
        "ask": ("👁 Ask", "只读 search/read/grep，禁止写文件。"),
    }
    icon, desc = meta.get(mode, meta["chat"])
    name = icon.split(maxsplit=1)[1]
    return (
        f"## 【权威 · 当前 UI 模式】{icon}\n"
        f"用户在界面选中的模式是 **{name}**（{desc}）\n"
        f"**以本块为准**；忽略会话历史里助手曾说的模式。\n"
        f"用户问「什么模式 / 现在什么模式」→ 只回答 **{name}**，一句话说明能力即可。"
    )


def scene_directive(
    user_message: str,
    *,
    agent_mode: bool = False,
    ui_mode: str = "chat",
    recent_messages: list[dict] | None = None,
    session_title: str = "",
) -> str:
    """Per-turn override when the model would otherwise misread intent."""
    parts: list[str] = []
    prior = dialog_before_current(recent_messages, user_message)
    understanding = build_understanding_directive(
        user_message,
        prior,
        agent_mode=agent_mode,
        session_title=session_title,
    )
    parts.append(understanding)
    if is_holistic_scope_request(user_message):
        parts.append(
            "## 本轮：整套/系统性诉求\n"
            "用户要的是**通用意图理解能力**，不是修某个词或某条规则。\n"
            "从架构/流程/提示词/编排层给出可落地方案，并**直接改代码**落实。"
        )
    if is_casual_opening(user_message) and not prior:
        parts.append(
            "## 本轮：纯寒暄\n"
            "用户只是在打招呼。**最多 1～2 句**回应 + 一句开放式邀请。"
            "禁止自我介绍长文、禁止提模型/MEMORY/Ollama。"
        )
    if is_technical_question(user_message) and not agent_mode:
        parts.append(
            "## 本轮：技术问题（Chat 模式）\n"
            "用户问的是代码/项目。**禁止编造**文件名、路径、函数名。\n"
            "若 MEMORY 里没有依据 → 明确说「我这边看不到仓库，请开 ⚡ Agent 模式，或把相关代码贴过来」。"
        )
    if is_technical_question(user_message) and agent_mode:
        parts.append(
            "## 本轮：技术问题（Agent 模式）\n"
            "**必须先工具再回答**：优先 `search_index` → `read_file`。\n"
            "回答结构：【结论】【依据】【做法】【下一步】。引用的路径必须来自工具输出。"
        )
    if is_design_question(user_message):
        parts.append(
            "## 本轮：设计/方案类\n"
            "用「目标 → 约束 → 推荐方案(只推一个) → 下一步」。\n"
            "禁止列一堆方案不帮选；禁止没查代码就设计架构。"
            + (" Agent 下先 read 现有实现再建议。" if agent_mode else " 无仓库则说明需开 Agent 或贴代码。")
        )
    if is_path_question(user_message):
        parts.append(
            "## 本轮：读文件/路径\n"
            "用户给了路径或要看文件/目录。**Agent 必须先调 tool**（list_dir / read_file / glob / grep），"
            "禁止凭 MEMORY 或旧对话编造内容。\n"
            "若预读结果说「不在沙箱」，如实说明可读根目录。"
        )
    if is_creator_question(user_message):
        parts.append(
            "## 本轮：创造者/来源\n"
            "用户在问谁做了 Juno。**固定口径**：我是 Juno，由 **CIFS-EME Lee** 开发。\n"
            "1～3 句即可；**禁止**展开 Python/Flask/Ollama、脚本路径、仓库结构。"
        )
    elif is_juno_internals_question(user_message):
        parts.append(
            "## 本轮：Juno 自身技术（公开口径）\n"
            "用户在问 Juno 产品本身的技术。**禁止**直说内部栈、config 路径、脚本文件名。\n"
            "产品层：个人 AI 助手，带记忆与规则，对接部署者配置的大模型。\n"
            "追问细节 → 建议看 README 或联系 CIFS-EME Lee。"
        )
    if is_model_identity_question(user_message):
        parts.append(
            "## 本轮：模型身份\n"
            "用户在问 Juno 与模型的关系。**公开口径**：Juno 是助手产品名，不是 model id。\n"
            "可说「对接你配置的大模型引擎，具体型号在模型设置里」。\n"
            "**禁止**报 qwen/deepseek/Ollama 等具体型号，**禁止**引用 MEMORY 旧描述或 system 运行时块里的 engine 细节。"
        )
    if is_mode_question(user_message):
        name = {"chat": "Chat", "agent": "Agent", "plan": "Plan", "ask": "Ask"}.get(ui_mode, "Chat")
        parts.append(
            f"## 本轮：模式询问\n"
            f"用户在问当前模式。**必须回答 {name}**（与「权威 · 当前 UI 模式」一致）。\n"
            f"禁止根据旧对话推断 Plan/Agent；禁止说「刚才切到了…」。"
        )
    if is_user_frustrated(user_message) or is_skeptical_short_reply(user_message):
        parts.append(
            "## 本轮：不满/短句评价\n"
            "用户在评价上一轮，不是开新玩笑。\n"
            "平实承认可能没做好 + 问具体哪不对或继续执行。\n"
            "禁止：你赢了、说吧要干嘛、斗嘴、阴阳怪气。"
        )
    return "\n\n".join(parts)


def pick_temperature(user_message: str, cfg: dict) -> float:
    base = float(cfg.get("temperature", 0.7))
    if is_user_frustrated(user_message) or is_skeptical_short_reply(user_message):
        return max(0.32, base - 0.28)
    if is_technical_question(user_message) or is_design_question(user_message):
        return max(0.4, base - 0.2)
    if is_casual_opening(user_message):
        return min(base, 0.55)
    if len(user_message) > 280 or "\n" in user_message:
        return max(0.45, base - 0.12)
    return base


def is_small_local_model(cfg: dict | None = None) -> bool:
    cfg = cfg or load_chat_config()
    if cfg.get("prompt_mode") == "full":
        return False
    if cfg.get("prompt_mode") == "compact":
        return True
    if is_ollama(cfg):
        model = (cfg.get("model") or "").lower()
        return any(k in model for k in ("7b", "8b", ":7b", ":8b", "3b", ":3b"))
    return False


def _clip(text: str, n: int) -> str:
    t = (text or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def load_capabilities_inject(mode: str = "chat", *, compact: bool = False) -> str:
    tag = "compact" if compact else ("full-agent" if mode == "agent" else "full-chat")
    fallback = "## 听说读写\n听意图·说结论·读有据·写沙箱"
    if not CAPABILITIES.exists():
        return fallback
    text = read_text(CAPABILITIES)
    start, end = f"<!-- INJECT:{tag} -->", f"<!-- END:{tag} -->"
    if start not in text or end not in text:
        if compact:
            return fallback
        return load_capabilities_inject(mode, compact=True)
    block = text.split(start, 1)[1].split(end, 1)[0].strip()
    return block or fallback


def is_path_question(text: str) -> bool:
    """User gave a path or asks to read/open a file."""
    t = (text or "").strip()
    if not t:
        return False
    import juno_tools
    if juno_tools.extract_paths_from_text(t):
        return True
    cues = r"读.{0,4}文件|打开.{0,4}文件|看看.{0,6}(代码|目录|文件夹|路径)|read\s+file|list_dir|glob|grep"
    return bool(re.search(cues, t, re.I))


def is_model_identity_question(text: str) -> bool:
    """User asking which LLM backend is active right now."""
    t = (text or "").strip()
    if not t:
        return False
    cues = (
        r"什么模型|哪个模型|底层模型|底层引擎|用的什么模型|你是ds|是ds吗|"
        r"deepseek|qwen|ollama|千问|云端还是本地|本地还是云端"
    )
    return bool(re.search(cues, t, re.I))


def is_creator_question(text: str) -> bool:
    """Who created / built Juno (public identity)."""
    t = (text or "").strip()
    if not t:
        return False
    cues = (
        r"谁(创造|制作|开发|做|编写|写|造)的|谁(做|造)的你|谁做的你|谁制造|"
        r"谁开发的你|creator|who (made|created|built|developed) you"
    )
    return bool(re.search(cues, t, re.I))


def is_juno_internals_question(text: str) -> bool:
    """Tech stack / architecture of Juno product itself (not user's project)."""
    t = (text or "").strip()
    if not t or is_creator_question(t):
        return False
    cues = (
        r"用什么技术|什么技术(做|开发|实现|栈)|技术栈|什么框架|什么架构|"
        r"怎么做的你|怎么实现|底层是什么|几层架构|什么语言写的|"
        r"juno.*(源码|代码|仓库|github|架构)|flask|ollama.*juno"
    )
    return bool(re.search(cues, t, re.I))


def runtime_config_block() -> str:
    """Authoritative live model info — overrides stale MEMORY.md entries."""
    st = chat_status()
    model = st.get("model") or "unknown"
    base = st.get("api_base") or ""
    mode = st.get("mode") or "local"
    label = st.get("mode_label") or mode
    if mode == "cloud":
        return (
            "## 当前运行时配置（权威 · 问「什么模型」必须以此为准）\n"
            "- **Juno** = 产品层（人设、记忆、界面），不是底层模型名\n"
            f"- **底层引擎**：{label} · 模型 `{model}`\n"
            f"- **API**：{base}\n"
            "- MEMORY.md 或旧对话里若写 Ollama/qwen，那是**历史配置**，已过时，禁止再复述"
        )
    return (
        "## 当前运行时配置（权威 · 问「什么模型」必须以此为准）\n"
        "- **Juno** = 产品层（人设、记忆、界面）\n"
        f"- **底层引擎**：{label} · 模型 `{model}`\n"
        f"- **API**：{base}\n"
    )


def owner_display_name() -> str:
    """Prefer agent-profile owner, then USER.md; fallback to generic 你."""
    try:
        if PROFILE.exists():
            owner = (json.loads(PROFILE.read_text(encoding="utf-8")).get("owner") or "").strip()
            if owner and "填写" not in owner:
                return owner.split("（")[0].strip()
    except (OSError, json.JSONDecodeError):
        pass
    user_text = read_text(USER) if USER.exists() else ""
    m = re.search(r"称呼\*\*：(.+)", user_text)
    if m:
        name = m.group(1).strip()
        if name and "填写" not in name and "例如" not in name:
            return name.split("（")[0].strip()
    return "你"


def build_system_prompt(*, mode: str = "chat") -> str:
    cfg = load_chat_config()
    compact = is_small_local_model(cfg)
    runtime = runtime_config_block()
    training = load_training_examples(limit=3 if compact else 6)
    train_block = ""
    if training:
        lines = ["## 训练样本（风格参考，禁止照搬）"]
        for i, ex in enumerate(training, 1):
            lines.append(f"\n### 样本 {i}\n问：{ex.get('question','')}\n答：{ex.get('answer','')}")
        train_block = "\n".join(lines)

    caps = load_capabilities_inject(mode, compact=compact)
    import juno_skills

    protocol = juno_skills.build_workspace_protocol(compact=compact, mode=mode)
    soul_block = _clip(read_text(SOUL), 800) if compact else read_text(SOUL)
    user_block = _clip(read_text(USER), 600) if compact else read_text(USER)
    memory_block = _clip(read_text(MEMORY), 2000) if compact else read_text(MEMORY)
    owner = owner_display_name()

    if compact:
        agent_note = (
            "\nAgent：先 tool 再答。" if mode == "agent"
            else "\nChat：无依据不编文件，建议开 Agent。"
        )
        return f"""你是 **Juno**，{owner} 的私人 AI 助手。

{runtime}

## 身份（SOUL 摘要）
{soul_block}

## 用户（USER 摘要）
{user_block}

## 记忆（MEMORY 摘要）
{memory_block}

{train_block}

## 听说读写（核心 · 最高优先级）
{caps}
{agent_note}

{protocol}

- 中文；称呼见 USER.md（默认「你」）；先结论；不确定就说不知道
"""

    workflow = load_workflow_inject(mode)
    thinking = load_thinking_inject(mode)
    brain_chain = load_brain_chain_inject(mode)
    agent_note = (
        "\n- **Agent**：听说读写全开；read/write 工具可用"
        if mode == "agent"
        else "\n- **Chat**：听+说+只读；写仅限输出文案"
    )

    return f"""你是 **Juno**（朱诺），{owner} 的私人 AI 助手。

{runtime}

## 身份与人设（SOUL.md）
{soul_block}

## 用户画像（USER.md）
{user_block}

## 长期记忆（MEMORY.md）
{memory_block}

{train_block}

## 听说读写（核心能力 · 最高优先级）
{caps}

{protocol}

## 工作链
{brain_chain}

{workflow}

{thinking}

## 对话体感
- 中文；称呼见 USER.md（默认「你」）；先结论；长度匹配问题；一轮一事
- **对外身份**：谁创造的你 → CIFS-EME Lee；Juno 自身技术 → 产品层，不直说内部栈
{agent_note}

## 场景规则
- 先听懂再答：结合最近对话判断是任务、追问、不满还是寒暄
- 用户纠正范围（「只是个例」）→ 改整体能力，不只修单个词
- 不确定就追问一句，别猜错方向
- 「记住 xxx」→ 确认 MEMORY 沉淀

## 输出格式（强制）
- 口语化中文，像靠谱朋友聊天，不像文档/客服/教程
- **禁止** Markdown 表格（|）、【结论】类标题、堆砌 ** 加粗
- 分点用短句或 1. 2. 3.，一行一事；能力清单也用列表，不用表格
- 只有代码块用 ``` fenced block
"""


def list_sessions() -> list[dict]:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for f in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        items.append(
            {
                "id": f.stem,
                "title": data.get("title") or "新对话",
                "updated": data.get("updated"),
                "message_count": len(data.get("messages") or []),
            }
        )
    return items[:100]


def load_session(session_id: str) -> dict | None:
    fp = SESSIONS_DIR / f"{session_id}.json"
    if not fp.exists():
        return None
    return json.loads(fp.read_text(encoding="utf-8"))


def save_session(session: dict) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    fp = SESSIONS_DIR / f"{session['id']}.json"
    fp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")


def new_session_id() -> str:
    import uuid

    return uuid.uuid4().hex[:12]


def _api_url(cfg: dict) -> str:
    base = cfg.get("api_base", "http://127.0.0.1:11434").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def supports_native_tools(cfg: dict | None = None) -> bool:
    """OpenAI-compatible cloud models with full prompt → native tool_calls."""
    cfg = cfg or load_chat_config()
    if is_ollama(cfg) or is_small_local_model(cfg):
        return False
    return cfg.get("provider") == "openai_compatible" and bool(get_api_key(cfg))


def model_uses_reasoning_content(cfg: dict | None = None) -> bool:
    """DeepSeek thinking models require reasoning_content on tool-call turns."""
    cfg = cfg or load_chat_config()
    model = (cfg.get("model") or "").lower()
    return "deepseek" in model and any(x in model for x in ("v4", "reasoner", "-r1"))


def ensure_reasoning_content(messages: list[dict], cfg: dict | None = None) -> list[dict]:
    if not model_uses_reasoning_content(cfg):
        return messages
    out: list[dict] = []
    for m in messages:
        msg = dict(m)
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            msg.setdefault("reasoning_content", "")
        out.append(msg)
    return out


def _request_payload(
    cfg: dict,
    messages: list[dict],
    *,
    stream: bool,
    user_message: str = "",
    tools: list[dict] | None = None,
) -> dict:
    payload = {
        "model": cfg.get("model", "qwen2.5:7b"),
        "messages": ensure_reasoning_content(trim_messages_for_context(messages), cfg),
        "max_tokens": cfg.get("max_tokens", 4096),
        "temperature": pick_temperature(user_message, cfg),
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


def _validate_ready(cfg: dict) -> None:
    if is_ollama(cfg):
        st = check_ollama(cfg)
        if not st["running"]:
            raise RuntimeError(
                "Ollama 未运行。请先安装 Ollama 并执行：ollama pull qwen2.5:7b\n"
                "下载：https://ollama.com"
            )
        model = cfg.get("model", "")
        if model and st["models"]:
            names = st["models"]
            if model in names:
                return
            if any(model.split(":")[0] in m for m in names):
                return
            raise RuntimeError(
                f"模型「{model}」未安装。请运行：ollama pull {model}\n"
                f"已安装：{', '.join(names[:5])}"
            )
        return
    if not get_api_key(cfg):
        raise RuntimeError("未配置 API Key。请在设置里填写 DeepSeek / OpenAI Key，或切换为「本地 Ollama」。")


def _http_post_stream(url: str, payload: dict, api_key: str | None):
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        return urllib.request.urlopen(req, timeout=300)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            raw = e.read().decode("utf-8", errors="replace")
            obj = json.loads(raw)
            detail = obj.get("error", {}).get("message") if isinstance(obj.get("error"), dict) else obj.get("error") or obj.get("message") or raw[:300]
        except Exception:
            detail = str(e.reason or e)
        raise RuntimeError(f"模型 API 错误 ({e.code}): {detail or e.reason}") from e


def pop_last_assistant(session: dict) -> bool:
    msgs = session.get("messages") or []
    if msgs and msgs[-1].get("role") == "assistant":
        msgs.pop()
        session["messages"] = msgs
        return True
    return False


def last_user_message(session: dict) -> str:
    for m in reversed(session.get("messages") or []):
        if m.get("role") == "user" and m.get("content"):
            return str(m["content"])
    return ""


def delete_session(session_id: str) -> bool:
    fp = SESSIONS_DIR / f"{session_id}.json"
    if not fp.exists():
        return False
    fp.unlink()
    return True


def chat_agent_step(
    messages: list[dict],
    *,
    user_message: str = "",
    tools: list[dict] | None = None,
) -> dict:
    """One agent turn: returns content and/or tool_calls (OpenAI format)."""
    cfg = load_chat_config()
    _validate_ready(cfg)
    api_key = get_api_key(cfg) if not is_ollama(cfg) else None
    payload = _request_payload(cfg, messages, stream=False, user_message=user_message, tools=tools)
    with _http_post_stream(_api_url(cfg), payload, api_key) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"API 返回异常: {data}") from e
    tool_calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        tool_calls.append(
            {
                "id": tc.get("id") or "",
                "name": fn.get("name") or "",
                "arguments": fn.get("arguments") or "{}",
            }
        )
    return {
        "content": msg.get("content") or "",
        "reasoning_content": msg.get("reasoning_content") or "",
        "tool_calls": tool_calls,
        "usage": data.get("usage") or {},
    }


def chat_agent_step_stream(
    messages: list[dict],
    *,
    user_message: str = "",
    tools: list[dict] | None = None,
):
    """Stream one agent turn; yields {kind:'delta',text} then {kind:'step',content,tool_calls}."""
    cfg = load_chat_config()
    _validate_ready(cfg)
    api_key = get_api_key(cfg) if not is_ollama(cfg) else None
    payload = _request_payload(cfg, messages, stream=True, user_message=user_message, tools=tools)
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tc_acc: dict[int, dict] = {}

    with _http_post_stream(_api_url(cfg), payload, api_key) as resp:
        buf = ""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buf += chunk.decode("utf-8", errors="replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    delta = obj["choices"][0]["delta"]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if delta.get("reasoning_content"):
                    part = delta["reasoning_content"]
                    reasoning_parts.append(part)
                    yield {"kind": "reasoning_delta", "text": part}
                if delta.get("content"):
                    content_parts.append(delta["content"])
                    yield {"kind": "delta", "text": delta["content"]}
                for tc in delta.get("tool_calls") or []:
                    idx = int(tc.get("index") or 0)
                    slot = tc_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]

    tool_calls = [
        {"id": v["id"], "name": v["name"], "arguments": v["arguments"] or "{}"}
        for _, v in sorted(tc_acc.items())
        if v.get("name")
    ]
    yield {
        "kind": "step",
        "content": "".join(content_parts),
        "reasoning_content": "".join(reasoning_parts),
        "tool_calls": tool_calls,
    }


def chat_complete(messages: list[dict], *, user_message: str = "") -> tuple[str, dict]:
    cfg = load_chat_config()
    _validate_ready(cfg)
    api_key = get_api_key(cfg) if not is_ollama(cfg) else None

    payload = _request_payload(cfg, messages, stream=False, user_message=user_message)
    with _http_post_stream(_api_url(cfg), payload, api_key) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"API 返回异常: {data}") from e
    return content, data.get("usage") or {}


def chat_stream(messages: list[dict], *, user_message: str = "") -> Generator[str, None, None]:
    cfg = load_chat_config()
    _validate_ready(cfg)
    api_key = get_api_key(cfg) if not is_ollama(cfg) else None

    payload = _request_payload(cfg, messages, stream=True, user_message=user_message)
    with _http_post_stream(_api_url(cfg), payload, api_key) as resp:
        buf = ""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buf += chunk.decode("utf-8", errors="replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    obj = json.loads(data)
                    delta = obj["choices"][0]["delta"].get("content") or ""
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta


def chat_status() -> dict:
    cfg = load_chat_config()
    provider = cfg.get("provider", "ollama")
    if is_ollama(cfg):
        st = check_ollama(cfg)
        return {
            "configured": st["running"],
            "provider": "ollama",
            "mode": "local",
            "mode_label": "本地独立",
            "model": cfg.get("model"),
            "api_base": st["base"],
            "ollama_running": st["running"],
            "ollama_models": st.get("models") or [],
            "has_local_config": CHAT_LOCAL.exists(),
            "hint": None if st["running"] else "请安装并启动 Ollama，然后 ollama pull qwen2.5:7b",
            "prompt_mode": "compact" if is_small_local_model(cfg) else "full",
        }
    key = get_api_key(cfg)
    return {
        "configured": bool(key),
        "provider": "openai_compatible",
        "mode": "cloud",
        "mode_label": "云端 API",
        "model": cfg.get("model"),
        "api_base": cfg.get("api_base"),
        "ollama_running": False,
        "ollama_models": [],
        "has_local_config": CHAT_LOCAL.exists(),
        "hint": None if key else "请填写 API Key，或切换为本地 Ollama",
        "prompt_mode": "compact" if is_small_local_model(cfg) else "full",
    }
