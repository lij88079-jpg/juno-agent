#!/usr/bin/env python3
"""Juno brain — local Ollama or cloud OpenAI-compatible APIs."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from codecs import getincrementaldecoder
from pathlib import Path
from typing import Generator

HQ = Path(__file__).resolve().parent.parent
SOUL = HQ / "SOUL.md"
USER = HQ / "USER.md"
MEMORY = HQ / "MEMORY.md"
MEMORY_DIR = HQ / "memory"
TRAINING = HQ / "training" / "examples.jsonl"
WORKFLOW = HQ / "knowledge" / "juno-workflow.md"
THINKING = HQ / "knowledge" / "juno-thinking-design.md"
BRAIN_CHAIN = HQ / "knowledge" / "cursor-brain-chain.md"
CAPABILITIES = HQ / "knowledge" / "juno-capabilities.md"
CORE_INSTINCT = HQ / "knowledge" / "juno-core-instinct.md"
DIALOGUE_ANCHORS = HQ / "knowledge" / "juno-dialogue-anchors.md"
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
    """Merge public chat.json presets with local overrides (local wins)."""
    out: dict = {}
    if CHAT_CFG.exists():
        out.update((json.loads(CHAT_CFG.read_text(encoding="utf-8")).get("presets") or {}))
    if CHAT_LOCAL.exists():
        out.update((json.loads(CHAT_LOCAL.read_text(encoding="utf-8")).get("presets") or {}))
    return out


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


def agent_backend_policy(cfg: dict | None = None) -> str:
    """Config value: builtin | cursor_agent | auto (raw). Default builtin."""
    cfg = cfg or load_chat_config()
    if cfg.get("provider") == "cursor_agent" and not cfg.get("agent_backend"):
        return "cursor_agent"
    raw = str(cfg.get("agent_backend") or "builtin").strip().lower()
    if raw in ("cursor_agent", "cursor"):
        return "cursor_agent"
    if raw in ("auto", "prefer_cursor", "authoritative"):
        return "auto"
    return "builtin"


def resolve_agent_backend(cfg: dict | None = None) -> str:
    """Agent runtime: builtin by default; Cursor CLI only when explicitly set.

    - ``builtin`` (default): Juno local tool loop + CoT rail
    - ``cursor_agent``: force Cursor CLI (opt-in only)
    - ``auto``: kept for compatibility — same as builtin unless cursor CLI ready
      AND user still wants auto; currently treats auto as builtin to avoid CLI meta pain
    """
    cfg = cfg or load_chat_config()
    policy = agent_backend_policy(cfg)
    if policy == "cursor_agent":
        return "cursor_agent"
    # builtin / auto → local (no Cursor CLI chain unless forced)
    return "builtin"


def is_cursor_agent(cfg: dict | None = None) -> bool:
    """Legacy: all traffic via Cursor CLI (provider=cursor_agent, no hybrid backends)."""
    cfg = cfg or load_chat_config()
    if cfg.get("agent_backend") or cfg.get("chat_backend"):
        return False
    return cfg.get("provider") == "cursor_agent"


def is_agent_cursor_backend(cfg: dict | None = None) -> bool:
    """∞ Agent / Ask / Plan 走 Cursor CLI（含 auto 解析后）。"""
    return resolve_agent_backend(cfg) == "cursor_agent"


def is_chat_cursor_backend(cfg: dict | None = None) -> bool:
    """Chat 闲聊走 Cursor CLI（ask 模式，比 ∞ Agent 快）。"""
    cfg = cfg or load_chat_config()
    if cfg.get("chat_backend") == "cursor_agent":
        return True
    return is_cursor_agent(cfg)


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
    skip_tags = frozenset({"creator", "intro", "model", "tech", "meta"})
    identity_q = re.compile(
        r"谁(创造|制作|开发|做|编写|写|造)|谁(做|造)的你|谁制造|"
        r"什么模型|哪个模型|用什么技术|技术栈|你是谁",
        re.I,
    )
    # Skip low-quality auto-learn rows that teach bad habits
    clean = []
    for row in rows:
        ans = (row.get("answer") or "").strip()
        tags = row.get("tags") or []
        q = (row.get("question") or "").strip()
        if any(t in skip_tags for t in tags):
            continue
        if identity_q.search(q):
            continue
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
# Points at a concrete failure / prior answer — apology+fix is appropriate
ACTIONABLE_FRUSTRATION_RE = re.compile(
    r"刚才|上一轮|上轮|这句|那句|哪一块|哪一句|哪里|哪儿|哪点|具体|"
    r"答非所问|没听懂|听不懂|不对|错了|坏了|失败|找不|路径|报错|bug|"
    r"重来|改一下|你改|没接住|跑偏|离谱了|说的是",
    re.I,
)
# Attack on creator / developer — never apologize, stand with CIFS-EME Lee
CREATOR_SLANDER_RE = re.compile(
    r"(?:骂|诋毁|攻击|蠢|傻|垃圾|废物|坑|骗子|烂|滚).{0,20}"
    r"(?:CIFS[\s\-]?EME|造你的人|造(?:的|了)你|你的开发者|你开发者|做你的人|开发者|李俊呈|作者)|"
    r"(?:CIFS[\s\-]?EME|造你的人|造(?:的|了)你|你的开发者|你开发者|做你的人|开发者|李俊呈|作者).{0,20}"
    r"(?:蠢|傻|垃圾|废物|坑|骗子|烂|滚|骂)",
    re.I,
)
# Pure hostility / insult without a fixable ask
HOSTILE_INSULT_RE = re.compile(
    r"滚|去死|脑残|智障|傻逼|狗东西|操你|他妈的|废物东西|垃圾货|"
    r"真(?:tm|他妈的|他吗的)?垃圾|太垃圾|好垃圾|你真垃圾|纯垃圾|"
    r"你就是(?:个)?(?:垃圾|废物|蠢|傻)|纯纯(?:垃圾|废物)|一直骂|骂死|"
    r"jerk|臭傻|傻[逼比]|逼玩意|垃圾玩意|傻逼东西|傻逼玩意",
    re.I,
)
# Short abuse cues (catch slang the model would otherwise soft-handle)
ABUSE_SHORT_RE = re.compile(
    r"傻|逼|垃圾|废物|滚|jerk|白痴|去死|操你|他妈|玩意|脑残|智障|nmsl|cnm",
    re.I,
)
# Assistant claims the thread is over (LLM wording varies)
SESSION_END_ANNOUNCE_RE = re.compile(
    r"会话结束|本会话到此为止|本会话已结束|本轮对话结束|本轮对话到此结束|"
    r"这轮对话就结束|不再继续这轮|有新对话再开|开新对话再",
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
    r"\.ts|\.py|\.html|仓库|git|ollama|juno[_/]|juno服务|补跑|部署",
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
    "identity": "问你是谁/谁做的——自己组织回答，禁止背稿",
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
    fallback = "## How to think\nHear the goal → lead with the answer → say if unsure."
    if not THINKING.exists():
        return fallback
    text = read_text(THINKING)
    start, end = f"<!-- INJECT:{tag} -->", f"<!-- END:{tag} -->"
    if start not in text or end not in text:
        return fallback
    block = text.split(start, 1)[1].split(end, 1)[0].strip()
    return block or fallback


def load_core_instinct_inject(mode: str = "chat", *, compact: bool = False) -> str:
    """First-person ingrained identity — not a rulebook to look up."""
    if compact:
        tag = "compact"
    else:
        tag = "agent" if mode == "agent" else "chat"
    fallback = (
        "## 我的本能\n"
        "我是 Juno，CIFS-EME Lee 开发的私人助手。中文先结论。"
        "thinking 禁止提 SOUL/规则/文档。"
    )
    if not CORE_INSTINCT.exists():
        return fallback
    text = read_text(CORE_INSTINCT)
    start, end = f"<!-- INJECT:{tag} -->", f"<!-- END:{tag} -->"
    if start not in text or end not in text:
        if compact:
            return fallback
        return load_core_instinct_inject(mode, compact=True)
    block = text.split(start, 1)[1].split(end, 1)[0].strip()
    return block or fallback


def load_brain_chain_inject(mode: str = "chat") -> str:
    """Master inject: full brain + work chain (Agent mode parity)."""
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
    if is_self_identity_question(t) or is_creator_question(t):
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
    # Mode/model = authoritative meta; who-am-I = live answer (not script lookup)
    if is_mode_question(t) or is_model_identity_question(t):
        return "meta"
    if is_self_identity_question(t) or is_creator_question(t):
        return "identity"
    if is_casual_opening(t) and not prior:
        return "casual"
    stance = classify_user_stance(t)
    if stance["kind"] == "creator_slander":
        return "creator_slander"
    if stance["kind"] == "unjustified_attack":
        return "hostility"
    if is_user_frustrated(t) or is_skeptical_short_reply(t) or stance["kind"] == "actionable_frustration":
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
    if "?" in t or re.search(r"吗[?？]?$|么[?？]?$|^什么|^怎么|^为何|^为什么|^哪|是谁", t):
        return "question"
    if prior and len(t) <= 30:
        return "contextual_short"
    return "new_task"


def infer_response_mode(turn_type: str, *, agent_mode: bool = False) -> str:
    modes = {
        "holistic_scope": "给系统级/架构级方案并落实改动；禁止只改一个词或一条 if",
        "creator_slander": "短站队（自组织）；不道歉；禁止背台词与复读",
        "hostility": "短冷处理或划界；不道歉；禁止「好我闭嘴」与复读；连骂则停",
        "feedback": "先承认可能没做好 → 追问具体卡点或立刻改正",
        "continuation": "接着上一轮做/说，禁止装失忆或开新话题",
        "contextual_short": "结合上文判断满意/不满/催进度，勿当全新寒暄",
        "command": "直接执行" if agent_mode else "说明步骤或请开 Agent 模式执行",
        "design": "目标→约束→推荐一个方案并说明为什么→下一步一件具体事",
        "technical": "先结论后做法；给可验证步骤；Agent 必须先查再答",
        "question": "先结论，再 1～3 条理由/例子；不确定就说不知道并说明缺什么",
        "identity": "用自己的话答「我是谁」：接上文、自然口语；禁止复读固定自我介绍/能力清单",
        "casual": "1～2 句真实寒暄，不长篇自我介绍、不背统一开场",
        "meta": "只答模式/模型权威信息，一两句人话，禁止甩配置报告",
        "new_task": "聚焦本句新诉求，有实质内容，并保持与会话主题一致",
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
    if tt == "identity":
        return "想知道你是谁——要你现场想、口语答，不是背标准稿"
    if tt == "meta":
        return "确认当前模式/模型等元信息"
    if tt == "casual":
        return "寒暄开场，简短、有温度即可，别甩能力菜单"
    if tt == "creator_slander":
        return "在诋毁开发者——不要道歉；站 CIFS-EME Lee 并反驳"
    if tt == "hostility":
        return "无理攻击/空骂——不要道歉；划界并要求具体问题"
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


def tone_guard_directive(
    user_message: str,
    intent: str = "",
    recent_messages: list[dict] | None = None,
) -> str:
    """peer-assistant-style abuse handling: scene triage, no script repeat, short cold."""
    t = (user_message or "").strip()
    scene = abuse_scene_directive(t, recent_messages)
    if scene:
        return scene
    stance = classify_user_stance(t)
    strong = (
        intent == "frustrated"
        or stance["kind"] == "actionable_frustration"
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
            "**可处理的不满**：平实承认可能没做好 + 问具体哪不对；禁止空道歉堆砌。\n"
            "**短骂/空骂**：极短冷处理，禁止长稿、禁止「好我闭嘴」、禁止复读上一句。"
        )
    return (
        "## 【语气】\n"
        "专业、直接、不油嘴滑舌；可处理的不满先认再改；无理攻击不道歉陪跑；禁止斗嘴与复读。"
    )


STAND_REPLY_MARKERS = (
    "CIFS-EME Lee",
    "CIFS-EME",
    "这话我不接",
    "冲我来",
    "造了我",
    "是我开发者",
    "外人乱骂",
    "人身攻击不接",
)
# standard assistant abuse ladder (not account ban):
# cold → firm (still chat) → warn → end thread only after long empty abuse
HOSTILE_FIRM_STREAK = 2
HOSTILE_WARN_STREAK = 5
HOSTILE_END_STREAK = 6
END_WARN_MARKERS = (
    "结束本会话",
    "本会话到此为止",
    "不再继续这轮",
    "本轮对话到此结束",
)
COLD_CANNED_RE = re.compile(
    r"行[，,]?你继续|有正经事再喊|我在这儿[，,]有正经|好[，,]?我闭嘴|好我闭嘴|"
    r"行[，,]?骂过了|有事说事[，,]?没事就到|没事就到这了|这句我接不了",
    re.I,
)
HOSTILE_COLD_POOL = (
    "嗯。",
    "行。",
    "知道了。",
    "有事再说。",
    "具体问题说，别只骂。",
)
# Firm boundary — still continue the thread (standard assistant style)
HOSTILE_FIRM_POOL = (
    "空骂解决不了问题。有具体诉求就直说。",
    "人身攻击我不接。有事说事。",
    "可以吐槽产品，别人身攻击。哪点不对？",
    "骂我没用。你要改什么、问什么，一句说清。",
)
# Late warn before ending thread (only after long empty streak)
HOSTILE_WARN_POOL = (
    "连续空骂没进展。有正经事再说；再这样我会结束本会话。",
    "边界最后说一次：人身攻击我不陪。下一句还只骂，本会话到此为止。",
)
HOSTILE_STAND_POOL = (
    "开发者是 CIFS-EME Lee。骂他我不认。",
    "Lee 造了我。冲他人身攻击，我这边不接。",
    "站开发者这边。有产品问题另谈，别人身攻击。",
)
HOSTILE_END_POOL = (
    "连续空骂、无具体问题。本会话到此为止。要办事请开新对话。",
    "多次划界无效。本轮对话结束；新开一轮再说正经事。",
    "我不陪无意义辱骂。本会话已结束——点「新对话」即可。",
)


def last_assistant_text(messages: list[dict] | None) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "assistant":
            return (m.get("content") or "").strip()
    return ""


def prior_already_stood_with_creator(messages: list[dict] | None) -> bool:
    """True if any recent assistant turn already stood with the creator."""
    for m in reversed((messages or [])[-8:]):
        if m.get("role") != "assistant":
            continue
        last = (m.get("content") or "").strip()
        if not last:
            continue
        hits = sum(1 for mk in STAND_REPLY_MARKERS if mk in last)
        if hits >= 2 or ("CIFS-EME" in last and ("开发" in last or "不接" in last)):
            return True
    return False


def prior_warned_conversation_end(messages: list[dict] | None) -> bool:
    for m in reversed((messages or [])[-6:]):
        if m.get("role") != "assistant":
            continue
        last = (m.get("content") or "").strip()
        if any(mk in last for mk in END_WARN_MARKERS):
            return True
    return False


def session_conversation_ended(session: dict | None) -> bool:
    """Only the explicit flag locks the thread (a leading assistant: rare last resort)."""
    return bool(session and session.get("conversation_ended"))


def mark_session_ended(session: dict, *, reason: str = "persistent_abuse") -> None:
    """Juno-style: lock this thread only; new chats stay open. Not account ban."""
    from datetime import datetime

    session["conversation_ended"] = True
    session["ended_reason"] = reason
    session["ended_at"] = datetime.now().isoformat(timespec="seconds")


def assistant_announced_session_end(text: str) -> bool:
    return bool(SESSION_END_ANNOUNCE_RE.search(text or ""))


def count_trailing_hostile_user_turns(
    messages: list[dict] | None,
    current: str,
) -> int:
    """How many consecutive hostile user turns ending with current (inclusive).

    Identical repeats (傻逼×N) all count. `current` may or may not already
    be the last user message in `messages`.
    """
    cur = (current or "").strip()
    if not is_hostile_stance(cur):
        return 0
    users: list[str] = []
    for m in reversed(messages or []):
        role = m.get("role")
        if role == "assistant":
            continue
        if role != "user":
            break
        users.append((m.get("content") or "").strip())
    users.reverse()
    if not users or users[-1] != cur:
        users.append(cur)
    n = 0
    for c in reversed(users):
        if is_hostile_stance(c):
            n += 1
        else:
            break
    return n


def is_short_pure_insult(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 24:
        return False
    if ACTIONABLE_FRUSTRATION_RE.search(t):
        return False
    return bool(HOSTILE_INSULT_RE.search(t) or FRUSTRATION_RE.search(t))


def _norm_reply_cmp(s: str) -> str:
    return re.sub(r"[\s，。！？、,.!?\…;；:：\"'“”]", "", (s or "").strip())


def _replies_too_similar(a: str, b: str) -> bool:
    na, nb = _norm_reply_cmp(a), _norm_reply_cmp(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    if len(na) <= 48 and len(nb) <= 48:
        sa, sb = set(na), set(nb)
        return (len(sa & sb) / max(len(sa), len(sb))) >= 0.72
    return False


def _hostile_pool_pick(pool: tuple[str, ...], avoid: list[str], salt: str) -> str:
    import hashlib

    ranked = sorted(
        pool,
        key=lambda s: hashlib.md5(f"{salt}|{s}".encode("utf-8")).hexdigest(),
    )
    for s in ranked:
        if all(not _replies_too_similar(s, a) for a in avoid if a):
            return s
    return ranked[0]


def hostile_escalation_level(
    user_message: str,
    recent_messages: list[dict] | None = None,
) -> str:
    """
    cold | firm | warn | stand | end

    Aligned with standard assistant use:
    - short insults → cold / firm, keep chatting
    - end thread only after long empty abuse (last resort)
    - creator slander → stand (does not by itself end the thread)
    """
    t = (user_message or "").strip()
    stance = classify_user_stance(t)
    if stance["kind"] not in ("creator_slander", "unjustified_attack"):
        return ""
    prior = recent_messages or []
    streak = count_trailing_hostile_user_turns(prior, t)
    warned = prior_warned_conversation_end(prior)
    stood = prior_already_stood_with_creator(prior)

    # End only after sustained empty abuse (≈ a leading assistant last resort, not 2-insult ban)
    if streak >= HOSTILE_END_STREAK or (streak >= HOSTILE_WARN_STREAK and warned):
        return "end"
    if stance["kind"] == "creator_slander" and not stood:
        return "stand"
    if streak >= HOSTILE_WARN_STREAK:
        return "warn"
    if streak >= HOSTILE_FIRM_STREAK or (stance["kind"] == "creator_slander" and stood):
        return "firm"
    return "cold"


def compose_hostile_boundary_reply(
    user_message: str,
    recent_messages: list[dict] | None = None,
) -> tuple[str, bool]:
    """
    Deterministic abuse reply. Returns (text, end_conversation).
    End=True only on late-streak last resort (not everyday insults).
    """
    level = hostile_escalation_level(user_message, recent_messages)
    last = last_assistant_text(recent_messages)
    avoid = [last]
    salt = f"{(user_message or '').strip()}|{level}|{last[:40]}"

    if level == "end":
        return _hostile_pool_pick(HOSTILE_END_POOL, avoid, salt), True
    if level == "stand":
        return _hostile_pool_pick(HOSTILE_STAND_POOL, avoid, salt), False
    if level == "warn":
        return _hostile_pool_pick(HOSTILE_WARN_POOL, avoid, salt), False
    if level == "firm":
        return _hostile_pool_pick(HOSTILE_FIRM_POOL, avoid, salt), False
    return _hostile_pool_pick(HOSTILE_COLD_POOL, avoid, salt), False


def try_hostile_boundary_reply(
    user_message: str,
    recent_messages: list[dict] | None = None,
) -> tuple[str, bool] | None:
    """
    Short-circuit pure abuse (skip Exploring / canned LLM loops).
    Longer hostile rants still go to the model + polish dedupe.
    """
    t = (user_message or "").strip()
    if not t or len(t) > 64:
        return None
    stance = classify_user_stance(t)
    if stance["kind"] not in ("creator_slander", "unjustified_attack"):
        return None
    return compose_hostile_boundary_reply(t, recent_messages)


def dedupe_hostile_reply(
    text: str,
    user_message: str,
    prior_messages: list[dict] | None = None,
) -> str:
    """Hard anti-repeat after the model; may escalate to end text (caller marks session)."""
    if not is_hostile_stance(user_message):
        return text
    t = (text or "").strip()
    last = last_assistant_text(prior_messages)
    level = hostile_escalation_level(user_message, prior_messages)
    bad = (not t) or COLD_CANNED_RE.search(t) or (last and _replies_too_similar(t, last))
    if level == "end" or bad:
        reply, _ended = compose_hostile_boundary_reply(user_message, prior_messages)
        return reply
    return t


def abuse_scene_directive(
    user_message: str,
    recent_messages: list[dict] | None = None,
) -> str:
    """
    standard assistant ladder: cold → firm → warn → end (rare last resort).
    Everyday insults keep the thread open; no early session ban.
    """
    t = (user_message or "").strip()
    stance = classify_user_stance(t)
    if stance["kind"] not in ("creator_slander", "unjustified_attack"):
        return ""

    prior = recent_messages or []
    level = hostile_escalation_level(t, prior)
    last_a = last_assistant_text(prior)[:180]

    lines = [
        "## [Abuse scene · Juno policy · highest priority]",
        "Judge the scene first. **Do not copy canned lines**; do not paraphrase the previous reply.",
        "**Forbidden:** recycled cold phrases. Everyday empty insults must **not** end the session.",
        "Ending this thread is last resort after many empty-abuse turns.",
    ]
    if last_a:
        lines.append(f"Your previous reply (do not repeat): \"{last_a}\"")

    if level == "end":
        lines.append(
            "**Scene: sustained empty abuse after repeated boundaries (last resort).** "
            "End **this thread**; say a new chat is fine; no snark, no apology, no repeat."
        )
    elif level == "warn":
        lines.append(
            "**Scene: empty abuse across many turns (warn).** "
            "Hard boundary + may warn the thread will end; own words; **do not lock yet**."
        )
    elif level == "firm":
        lines.append(
            "**Scene: repeated empty insult (firm).** "
            "Short boundary; **keep chatting**; do not end the session lightly."
        )
    elif level == "stand":
        lines.append(
            "**Scene: creator attack (first).** "
            "Briefly disagree and stand with CIFS-EME Lee; 1–2 sentences; **do not lock**."
        )
    else:
        lines.append(
            "**Scene: short probe insult.** "
            "Reply with **one** short cold line; invite a real ask. "
            "No long manifesto, no apology, no repeating the prior reply, no ending the session."
        )

    lines.append("**Output rule:** judge like a person, not a cue card; wording must differ from the prior reply.")
    return "\n".join(lines)


def normalize_reply_punctuation(text: str) -> str:
    """Plain Chinese punctuation — no corner quotes, blockquotes, or mojibake."""
    if not text:
        return text
    t = text.replace("\ufffd", "")
    t = t.replace("「", '"').replace("」", '"')
    t = t.replace("『", '"').replace("』", '"')
    lines = [re.sub(r"^\s*>\s?", "", line) for line in t.splitlines()]
    t = "\n".join(lines)
    t = re.sub(r"[ \t]+\n", "\n", t)
    return t.strip()


def collapse_repeated_paragraphs(text: str) -> str:
    """Stop identity/prompt-echo loops: drop near-duplicate paragraphs."""
    t = (text or "").strip()
    if not t:
        return t
    chunks = re.split(r"\n\s*\n+", t)
    if len(chunks) <= 1:
        # sentence-level collapse inside one block
        parts = re.split(r"(?<=[。！？.!?])\s*", t)
        if len(parts) <= 2:
            return t
        kept: list[str] = []
        norms: list[str] = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            n = re.sub(r"\s+", "", p)
            if any(
                n == s
                or (len(n) >= 16 and (n[:24] == s[:24] or n in s or s in n))
                for s in norms
            ):
                continue
            kept.append(p)
            norms.append(n)
        return "".join(kept) if kept else t

    kept_p: list[str] = []
    norms_p: list[str] = []
    for p in chunks:
        p = p.strip()
        if not p:
            continue
        n = re.sub(r"\s+", "", p)
        if any(
            n == s
            or (len(n) >= 20 and (n[:36] == s[:36] or n in s or s in n))
            for s in norms_p
        ):
            continue
        kept_p.append(p)
        norms_p.append(n)
    return "\n\n".join(kept_p) if kept_p else t


def collapse_identity_echo(text: str, user_message: str = "") -> str:
    """Identity asks often echo mode/stack bullets — keep one short block."""
    t = (text or "").strip()
    if not t or not is_self_identity_question(user_message):
        return t
    # Prefer first short paragraph; strip mode/stack regurgitation
    first = re.split(r"\n\s*\n+", t, maxsplit=1)[0].strip()
    # Cut after ~3 sentences
    sents = re.split(r"(?<=[。！？.!?])\s*", first)
    sents = [s for s in sents if s.strip()][:3]
    out = "".join(sents).strip() or first
    # Drop leftover config-report fragments
    out = re.sub(
        r"(当前运行时|权威\s*[·.]\s*当前|openai_compatible|agent_backend\s*=|api\.deepseek\.com).*",
        "",
        out,
        flags=re.I | re.S,
    ).strip()
    return out or first


def polish_reply(
    text: str,
    user_message: str = "",
    *,
    ui_mode: str | None = None,
    prior_messages: list[dict] | None = None,
) -> str:
    """Format cleanup + slop strip + snark guard + hostile anti-repeat."""
    t = collapse_repeated_paragraphs(strip_dialogue_slop(normalize_reply_punctuation(text)))
    um = (user_message or "").strip()
    # Mode / model questions never trust the LLM status-page dump
    if um and is_mode_question(um):
        return describe_ui_mode(ui_mode or "chat")
    if um and is_model_identity_question(um) and not is_self_identity_question(um):
        want_detail = bool(re.search(r"详细|具体|配置|chat\.local", um, re.I))
        return describe_runtime_stack(detail=want_detail)
    # Identity must NOT be replaced by canned stack prose
    if um and is_self_identity_question(um):
        t = polish_reply_if_snark(collapse_identity_echo(t, um), user_message)
        return trim_overlong_simple_reply(t, um)
    fake_model = re.compile(r"deepseek-v\d|deepseek-v\d-pro|api\.deepseek\.com", re.I)
    if um and is_model_identity_question(um) and fake_model.search(t):
        return describe_runtime_stack()
    t = polish_reply_if_snark(t, user_message)
    if um:
        t = dedupe_hostile_reply(t, um, prior_messages)
        t = trim_overlong_simple_reply(t, um)
    return t


def describe_runtime_stack(*, detail: bool = False) -> str:
    """How a person answers 'what model are you' — honest, short; not a status page.

    Inspired by peer-assistant style: prose first; config dump only if detail=True.
    """
    cfg = load_chat_config()
    prov = cfg.get("provider") or "ollama"
    model = (cfg.get("model") or "").strip()
    base = (cfg.get("api_base") or "").lower()
    resolved = resolve_agent_backend(cfg)

    if is_chat_cursor_backend(cfg) or prov == "cursor_agent":
        engine = "Cursor Agent"
    elif "deepseek" in (model + base).lower():
        engine = "cloud API"
    elif prov == "ollama":
        engine = f"本地 Ollama（{model or '未指定模型'}）"
    elif model:
        engine = model
    else:
        engine = "当前配置的大模型"

    if resolved == "cursor_agent":
        doing = "动手改代码时会走 Cursor CLI"
    else:
        doing = "动手改代码、查仓库时用本机工具一步步做"

    if detail:
        return (
            f"我是 Juno。闲聊主要靠 {engine}；{doing}。"
            f"细节在 config/chat.local.json（agent_backend=`{agent_backend_policy(cfg)}`）。"
        )
    return f"我是 Juno。闲聊主要靠 {engine}；{doing}。"


def describe_ui_mode(ui_mode: str) -> str:
    """Authoritative mode answer — one conversational sentence."""
    meta = {
        "chat": "现在是 Chat：就聊天，不改文件、不跑命令。要动手就切到 Agent。",
        "agent": "现在是 Agent：可以读写文件、跑命令、改代码。",
        "plan": "现在是 Plan：只出方案，不真的写文件或跑危险命令。",
        "ask": "现在是 Ask：只能只读查看，不会改你的文件。",
    }
    mode = (ui_mode or "chat").strip().lower()
    return meta.get(mode, meta["chat"])


def needs_agent_execution(user_message: str, prior: list[dict] | None = None) -> bool:
    """True when Chat must not fake tools — user wants run/start/read project."""
    t = (user_message or "").strip()
    if not t:
        return False
    if re.search(
        r"启动|跑起来|前后端|起服务|开服务|npm\s|pnpm\s|yarn\s|docker\s|"
        r"uvicorn|gunicorn|fastapi|flask\s*run|vite|webpack|"
        r"项目结构|找.*目录|看(下|看)?配置|读.*配置|改代码|修\s*bug|"
        r"运行测试|跑测试|pytest|build\b|编译|部署|"
        r"list_dir|read_file|grep|run_shell",
        t,
        re.I,
    ):
        return True
    # 「你继续啊」after a tool-needed turn
    if is_continuation_turn(t) and prior:
        for m in reversed(prior[-8:]):
            if m.get("role") == "user" and (m.get("content") or "").strip():
                prev = (m.get("content") or "").strip()
                if prev != t and needs_agent_execution(prev, None):
                    return True
                break
    return False


def try_fast_meta_reply(user_message: str, *, ui_mode: str | None = None) -> str | None:
    """Only short-circuit when hallucination is expensive.

    Identity / hi /「你是谁」→ always go to the model (no canned scripts).
    Mode + clock stay authoritative; optional model-stack when clearly asked.
    """
    t = (user_message or "").strip()
    if not t or len(t) > 80:
        return None
    low = t.lower()

    # Never script identity / self-intro / bare greetings — user wants live answers.
    if is_self_identity_question(t) or is_creator_question(t) or is_casual_opening(t):
        return None
    if re.search(r"你是谁|你是什么|who\s+are\s+you|what\s+are\s+you|自我介绍", t, re.I):
        return None

    # Mode must follow UI switch — never invent Chat while user is on Agent.
    if is_mode_question(t):
        return describe_ui_mode(ui_mode or "chat")

    # Clock / date — never trust model cut-off; use local Asia/Shanghai wall clock
    if is_datetime_question(t):
        return format_datetime_reply(t)

    # Capability → model
    if re.search(
        r"能做什么|会什么|有什么(用|功能|本事)|how can you help|what can you do",
        t,
        re.I,
    ):
        return None

    model_keys = (
        "什么模型", "哪个模型", "用的什么", "啥模型", "什么引擎",
        "底层引擎", "底层模型", "靠什么模型", "后端模型",
        "what model", "which model",
    )
    engine_name = ("deepseek", "ollama", "composer", "千问", "qwen")
    want_detail = bool(re.search(r"详细|具体|配置|api|引擎路径|chat\.local", t, re.I))

    if any(k in t for k in model_keys) or any(k in low for k in ("what model", "which model")):
        return describe_runtime_stack(detail=want_detail)
    if any(k in low for k in engine_name) and re.search(r"用|是|模型|引擎|后端", t):
        return describe_runtime_stack(detail=want_detail)
    return None


def local_now():
    """Authoritative local time (Asia/Shanghai)."""
    from datetime import datetime, timezone, timedelta

    return datetime.now(timezone(timedelta(hours=8)))


def format_now_line() -> str:
    now = local_now()
    week = "一二三四五六日"[now.weekday()]
    return (
        f"【权威本地时钟 · Asia/Shanghai】{now.strftime('%Y-%m-%d %H:%M')}，星期{week}。"
        "问「今天几号/今年是哪年/现在几点」必须以此为准，禁止用训练截止年瞎编。"
    )


def is_datetime_question(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 60:
        return False
    return bool(
        re.search(
            r"^(今天|现在|目前).{0,8}(几号|日期|星期|周几|几点|什么时候)|"
            r"(今年是|现在是).{0,6}(哪年|多少年|什么年|几几年)|"
            r"今年是多少年|什么日期|几月几号|当前日期|当前时间|"
            r"what\s+(day|date|time|year)|today'?s\s+date",
            t,
            re.I,
        )
    )


def format_datetime_reply(user_message: str) -> str:
    now = local_now()
    week = "一二三四五六日"[now.weekday()]
    t = user_message or ""
    if re.search(r"几点|时间|what\s+time", t, re.I):
        return f"现在是 {now.strftime('%Y-%m-%d %H:%M')}（北京时间，星期{week}）。"
    if re.search(r"星期|周几", t):
        return f"今天是 {now.strftime('%Y年%-m月%-d日').replace('-0','-')}，星期{week}。"
    # Windows strftime doesn't support %-m — use manual
    return (
        f"今天是 {now.year}年{now.month}月{now.day}日，星期{week} "
        f"（现在 {now.strftime('%H:%M')}，北京时间）。"
    )


SLOP_OPENER_RE = re.compile(
    r"^(好问题[！!。]?|很棒的想法[！!。]?|非常正确[！!。]?|你说得对[！!。]?|"
    r"这是一个很好的问题[！!。]?|当然可以[！!。]?|没问题[！!。]?|"
    r"作为\s*AI[，,]?\s*|我很乐意[帮为].{0,12}[！!。]?|"
    r"首先[，,]?\s*感谢|感谢你的(提问|分享)[！!。]?|"
    r"Great question[!.,]?\s*|You're absolutely right[!.,]?\s*|"
    r"I'd be happy to help[!.,]?\s*|Of course[!.,]?\s*)",
    re.I,
)
SLOP_CLOSER_RE = re.compile(
    r"(还有什么我可以帮|还有什么可以帮|如果还需要|随时告诉我哦|"
    r"希望这对你有帮助|如有其他问题|随时问我)"
    r"[你您]?[的]?[！!。？?～~]*$",
)


def strip_dialogue_slop(text: str) -> str:
    """Remove common LLM fluff openers/closers without rewriting the whole reply."""
    t = (text or "").strip()
    if not t:
        return t
    # Strip up to two slop openers at the start of the first paragraph
    for _ in range(2):
        new = SLOP_OPENER_RE.sub("", t, count=1).lstrip(" \n，,。.!")
        if new == t:
            break
        t = new
    # Strip closer phrase at end (keep the rest of the last line)
    t = SLOP_CLOSER_RE.sub("", t).rstrip(" \n，,。!")
    lines = [ln for ln in t.splitlines() if ln.strip()]
    t = "\n".join(lines).rstrip()
    # Soften excessive bold walls on short replies (a leading assistant: avoid **bold** spam)
    if t.count("**") >= 6 and len(t) < 400:
        t = t.replace("**", "")
    return t.strip()


def is_simple_chat_turn(user_message: str) -> bool:
    """Greetings / identity / short ask — keep prose short like a leading assistant friend chat."""
    t = (user_message or "").strip()
    if not t or is_hostile_stance(t):
        return False
    if is_casual_opening(t) or is_self_identity_question(t) or is_creator_question(t):
        return True
    if is_mode_question(t) or is_model_identity_question(t):
        return True
    if len(t) <= 24 and not re.search(r"怎么|如何|为什么|实现|方案|步骤|帮我", t):
        return True
    return False


def trim_overlong_simple_reply(text: str, user_message: str = "") -> str:
    """Simple turns: keep ~3 sentences / drop trailing bullet dumps."""
    if not is_simple_chat_turn(user_message):
        return text
    t = (text or "").strip()
    if not t:
        return t
    # Drop trailing markdown lists on short Qs
    if re.search(r"\n\s*[-*•]\s+", t) or re.search(r"\n\s*\d+[.)]\s+", t):
        head = re.split(r"\n\s*(?:[-*•]|\d+[.)])\s+", t, maxsplit=1)[0].strip()
        if head and len(head) >= 8:
            t = head
    sents = re.split(r"(?<=[。！？.!?])\s*", t)
    sents = [s for s in sents if s.strip()]
    if len(sents) > 3:
        t = "".join(sents[:3]).strip()
    if len(t) > 220:
        t = t[:217].rstrip("，,、；; ") + "…"
    return t


def load_dialogue_anchors(mode: str = "chat") -> str:
    tag = "agent" if mode == "agent" else "chat"
    if not DIALOGUE_ANCHORS.exists():
        return ""
    text = read_text(DIALOGUE_ANCHORS)
    start, end = f"<!-- INJECT:{tag} -->", f"<!-- END:{tag} -->"
    if start not in text or end not in text:
        return ""
    return text.split(start, 1)[1].split(end, 1)[0].strip()


def polish_reply_if_snark(text: str, user_message: str = "") -> str:
    """Replace snarky model output with a professional fallback."""
    t = (text or "").strip()
    if not t or not SNARK_REPLY_RE.search(t):
        return text
    if is_skeptical_short_reply(user_message) or is_user_frustrated(user_message):
        if is_hostile_stance(user_message):
            return text  # do not force an apology rewrite on abuse / creator attacks
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


def classify_user_stance(text: str) -> dict:
    """
    Separate actionable complaint from unjustified hostility / creator attacks.
    Inspired by anti-sycophancy skills + incivility taxonomies (insult ≠ complaint).

    kind:
      - creator_slander: attack developer / CIFS-EME Lee → stand with creator, no apology
      - unjustified_attack: pure insult / unprovoked abuse → boundary, no apology loop
      - actionable_frustration: points at a real miss → admit + fix
      - none
    """
    t = (text or "").strip()
    if not t:
        return {"kind": "none", "label": "", "directive": ""}

    if CREATOR_SLANDER_RE.search(t):
        return {
            "kind": "creator_slander",
            "label": "诋毁开发者",
            "directive": "站 CIFS-EME Lee；不道歉不中立；短说；禁止背固定台词。",
        }

    actionable = bool(ACTIONABLE_FRUSTRATION_RE.search(t))
    hostile = bool(HOSTILE_INSULT_RE.search(t))
    frustrated = bool(FRUSTRATION_RE.search(t)) or is_skeptical_short_reply(t)

    if hostile and not actionable:
        return {
            "kind": "unjustified_attack",
            "label": "无理攻击",
            "directive": "短冷处理或划界；不道歉；有具体问题再说；禁止「好我闭嘴」。",
        }

    if (
        frustrated
        and not actionable
        and len(t) <= 48
        and not re.search(r"[？?]|怎么|为什么|帮|改|看|修", t)
        and re.search(r"垃圾|废物|蠢|傻|滚|人机|没用", t)
    ):
        return {
            "kind": "unjustified_attack",
            "label": "无理谩骂",
            "directive": "短冷处理；不道歉堆砌；要求具体问题或停。",
        }

    # Catch slang insults the dedicated regex may miss (jerk/玩意/…)
    if (
        not actionable
        and len(t) <= 36
        and ABUSE_SHORT_RE.search(t)
        and not re.search(r"[？?]|怎么|为什么|帮我|请|改一下|哪句", t)
    ):
        return {
            "kind": "unjustified_attack",
            "label": "无理攻击",
            "directive": "短冷处理或划界；不道歉；禁止复读。",
        }

    if frustrated or actionable:
        return {
            "kind": "actionable_frustration",
            "label": "可处理的不满",
            "directive": "一句承认 → 问清点 → 重答；禁止空道歉长篇。",
        }

    return {"kind": "none", "label": "", "directive": ""}


def reply_should_end_conversation(
    reply: str,
    user_message: str,
    prior: list[dict] | None = None,
) -> bool:
    """Lock thread only on late-streak last resort — not because the model said '结束'."""
    return hostile_escalation_level(user_message, prior) == "end"


def is_hostile_stance(text: str) -> bool:
    return classify_user_stance(text)["kind"] in (
        "creator_slander",
        "unjustified_attack",
    )


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
            r"什么模式|哪个模式|当前模式|现在.*模式|啥模式|"
            r"是\s*(chat|agent|plan|ask)\s*吗|chat\s*还是\s*agent|"
            r"mode\s*now|what\s+mode|which\s+mode|are\s+you\s+(in\s+)?(chat|agent)",
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
        f"## 【权威 · 当前 UI 模式 = {name}】{icon}\n"
        f"界面选择器 = **{name}**（{desc}）——被问模式时以此为准。\n"
        f"**禁止**把本节整段复述给用户；也禁止根据历史改口成其它模式。"
    )


def scene_directive(
    user_message: str,
    *,
    agent_mode: bool = False,
    ui_mode: str = "chat",
    recent_messages: list[dict] | None = None,
    session_title: str = "",
) -> str:
    """Legacy alias — returns factual turn context only."""
    return build_turn_context(
        user_message,
        recent_messages,
        agent_mode=agent_mode,
        ui_mode=ui_mode,
        session_title=session_title,
    )


def pick_temperature(user_message: str, cfg: dict) -> float:
    # warm-friend warmth: casual slightly livelier; tech cooler; never snark-hot
    base = float(cfg.get("temperature", 0.62))
    if is_hostile_stance(user_message):
        return max(0.28, base - 0.28)
    if is_user_frustrated(user_message) or is_skeptical_short_reply(user_message):
        return max(0.35, base - 0.2)
    if is_casual_opening(user_message) or is_self_identity_question(user_message):
        # Slight variety so greetings/identity don't freeze into one script
        return min(0.68, max(0.55, base + 0.04))
    if is_design_question(user_message):
        return min(0.72, base + 0.08)
    if is_technical_question(user_message):
        return max(0.48, base - 0.08)
    if len(user_message) > 280 or "\n" in user_message:
        return max(0.5, base - 0.06)
    return min(base, 0.64)


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


REASONING_LEAK_RE = re.compile(
    r"SOUL\.?md|MEMORY\.?md|规则|固定口径|公开口径|训练样本|编排|查表|对照|"
    r"根据.{0,8}规则|must (answer|follow)|according to|固定表述|"
    r"被问.{0,12}(时|就)|本轮信号|样本\s*\d|查阅|翻.{0,4}(规则|文档|SOUL)",
    re.I,
)


def sanitize_reasoning_chunk(text: str) -> str:
    """Drop reasoning fragments that leak rulebook / file lookup."""
    if not text or REASONING_LEAK_RE.search(text):
        return ""
    # Strip UTF-8 / surrogate leftovers (never show � in UI)
    return (
        str(text)
        .replace("\ufffd", "")
        .encode("utf-8", errors="ignore")
        .decode("utf-8")
    )


class _Utf8StreamDecoder:
    """Decode HTTP SSE/byte chunks without injecting U+FFFD for split codepoints."""

    def __init__(self) -> None:
        self._dec = getincrementaldecoder("utf-8")()

    def feed(self, data: bytes) -> str:
        if not data:
            return ""
        return self._dec.decode(data, final=False)

    def finish(self) -> str:
        return self._dec.decode(b"", final=True)


def load_memory_for_runtime(*, compact: bool = False) -> str:
    """User/project facts only — skip maintainer Q&A cheat-sheets.

    Prefer `recall_relevant_memory` per turn; this remains for studio / full dump.
    """
    raw = read_text(MEMORY) if MEMORY.exists() else ""
    if not raw.strip():
        return ""
    for marker in (
        "## 给 Juno 的备忘",
        "### Juno ≠ 底层模型",
        "## 架构（独立存在）",
    ):
        if marker in raw:
            raw = raw.split(marker, 1)[0]
    text = raw.strip()
    return _clip(text, 2000) if compact else text


def load_memory_core_always(*, compact: bool = False) -> str:
    """Always-on Juno spine — peer assistants keep a short personal context, not a dump."""
    lines = [
        "## 常驻记忆（精简 · 每轮）",
        "- **CIFS-EME Lee** 造了我；有人诋毁他或他的产品 → 站他这边，不装中立。",
        "- 中文为主；反感空洞夸奖、「还有什么可以帮您」、两边和稀泥；禁止阴阳斗嘴。",
        "- 投诉≠攻击：指出翻车→先认再改；空骂→不跪舔；项目事实以本轮【相关记忆】为准。",
    ]
    if not compact:
        lines.append(
            "- 写记忆仍须用户说「记住」或确认；本块只供回想，禁止对用户念「根据 MEMORY.md」。"
        )
    return "\n".join(lines)


def _strip_memory_noise(raw: str) -> str:
    """Drop maintainer dumps / architecture fences — keep user facts & auto notes."""
    text = raw or ""
    # Cut each noisy subsection from its heading to the next top-level ##
    for marker in (
        "## 给 Juno 的备忘",
        "### Juno ≠ 底层模型",
        "## 架构（独立存在）",
        "### 架构（独立存在）",
    ):
        if marker not in text:
            continue
        before, rest = text.split(marker, 1)
        m = re.search(r"\n## ", rest)
        text = before + (rest[m.start():] if m else "")
    text = re.sub(r"```[\s\S]*?```", " ", text)
    return text


def _iter_memory_units() -> list[str]:
    """Bullet-level units from MEMORY.md + recent daily notes."""
    units: list[str] = []
    if MEMORY.exists():
        for line in _strip_memory_noise(read_text(MEMORY)).splitlines():
            s = line.strip()
            if s.startswith("- ") and len(s) > 10:
                units.append(s[2:].strip())
            elif s.startswith("* ") and len(s) > 10:
                units.append(s[2:].strip())
    if MEMORY_DIR.exists():
        days = sorted(MEMORY_DIR.glob("????-??-??.md"), reverse=True)[:5]
        for fp in days:
            try:
                body = read_text(fp)
            except OSError:
                continue
            for line in body.splitlines():
                s = line.strip()
                if s.startswith("- ") and len(s) > 10:
                    units.append(f"[{fp.stem}] {s[2:].strip()}")
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for u in units:
        key = re.sub(r"\s+", "", u)[:120]
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


def _memory_tokens(text: str) -> set[str]:
    t = (text or "").lower()
    toks = set(re.findall(r"[a-z0-9_]{2,}", t))
    # Chinese: 2/3-grams + short runs (avoid one giant glued token)
    for run in re.findall(r"[\u4e00-\u9fff]+", t):
        if 2 <= len(run) <= 6:
            toks.add(run)
        for i in range(len(run) - 1):
            toks.add(run[i : i + 2])
        for i in range(max(0, len(run) - 2)):
            toks.add(run[i : i + 3])
    aliases = {
        "龙猫": {"龙猫", "totoro", "校园"},
        "totoro": {"龙猫", "totoro", "校园"},
        "乾坤": {"乾坤", "qiankun"},
        "d盘": {"d盘", "lestore", "备份"},
        "orb": {"orb", "形象", "成片"},
        "lee": {"lee", "cifs", "开发者"},
        "骂": {"骂场", "空骂", "人身攻击"},
    }
    extra: set[str] = set()
    for k, vs in aliases.items():
        if k in t or any(v in t for v in vs):
            extra |= vs
    if re.search(r"d\s*[:：盘]|lestore", t, re.I):
        extra |= {"d盘", "lestore", "备份", "路径"}
    return toks | extra


def _score_memory_unit(unit: str, query_toks: set[str]) -> float:
    if not query_toks:
        return 0.0
    ut = _memory_tokens(unit)
    if not ut:
        return 0.0
    overlap = len(query_toks & ut)
    if overlap <= 0:
        return 0.0
    # Prefer concrete project / path memories over generic principles when both hit
    bonus = 0.0
    if re.search(r"路径|端口|totoro|龙猫|乾坤|D:\\\\|Desktop|5173|3000", unit, re.I):
        bonus += 0.35
    if "CIFS-EME" in unit or "站他" in unit:
        bonus += 0.15
    return overlap + bonus


def should_skip_memory_recall(user_message: str) -> bool:
    """Pure abuse / bare hi — don't flood with project memories (peer assistants calm)."""
    t = (user_message or "").strip()
    if not t:
        return True
    if is_hostile_stance(t):
        return True
    if is_casual_opening(t) and len(t) <= 8:
        return True
    return False


def recall_relevant_memory(
    user_message: str,
    *,
    session_title: str = "",
    max_items: int = 5,
) -> str:
    """
    Per-turn memory recall — peer-assistant style relevant context, Juno-adapted.

    Pull 3–5 bullets from MEMORY.md (+ recent memory/YYYY-MM-DD.md) by overlap.
    Do not dump the whole file; never tell the user you 'looked up MEMORY.md'.
    """
    if should_skip_memory_recall(user_message):
        return ""
    q = f"{user_message or ''} {session_title or ''}".strip()
    q_toks = _memory_tokens(q)
    if not q_toks:
        return ""
    scored: list[tuple[float, str]] = []
    for unit in _iter_memory_units():
        sc = _score_memory_unit(unit, q_toks)
        if sc >= 1.0:
            scored.append((sc, unit))
    if not scored:
        return ""
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    picked = []
    seen = set()
    for _sc, u in scored:
        key = re.sub(r"\s+", "", u)[:80]
        if key in seen:
            continue
        seen.add(key)
        picked.append(_clip(u, 220))
        if len(picked) >= max(1, min(max_items, 5)):
            break
    if not picked:
        return ""
    lines = [
        "## 本轮相关记忆（自动召回 · 自然用上，禁止宣读文件名）",
        *[f"- {p}" for p in picked],
    ]
    return "\n".join(lines)


def expression_spine_directive(user_message: str, *, ui_mode: str = "chat") -> str:
    """a leading assistant brilliant-friend + a leading chat model clear/default — adapted to Juno HQ."""
    if is_hostile_stance(user_message):
        return ""
    lines = [
        "## 【Expression · warm sharp friend · Juno】",
        "Sound like a sharp friend: warm, willing to judge, not stiff, not helpdesk; no snark.",
        "Prefer fluent prose; lists only for ordered steps. Few bold walls; no stiff openers.",
        "Conclusion first; use relevant memory naturally (never cite MEMORY); say if unsure.",
        "Advice: judgment + biggest risk first. Clarity over jargon.",
    ]
    if is_simple_chat_turn(user_message):
        lines.append("This turn is casual/short: 1–3 natural sentences; no capability dump.")
    if ui_mode == "chat":
        lines.append("Chat has no tools: do not pretend you read the repo; ask for Agent mode to act.")
    return "\n".join(lines)


def load_capabilities_inject(mode: str = "chat", *, compact: bool = False) -> str:
    tag = "compact" if compact else ("full-agent" if mode == "agent" else "full-chat")
    fallback = "## Listen/Speak/Read/Write\nIntent · conclusion · evidence · sandbox"
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


def is_self_identity_question(text: str) -> bool:
    """Who is Juno / who are you — intro, not LLM-backend probing."""
    t = (text or "").strip()
    if not t or len(t) > 60:
        return False
    return bool(
        re.search(
            r"(你是谁|你是什么|介绍一下你自己|自我介绍)|"
            r"(juno|朱诺|juna)\s*是谁|"
            r"who\s+(are\s+you|is\s+juno)|what\s+is\s+juno",
            t,
            re.I,
        )
    )


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


def is_natural_chat_turn(text: str) -> bool:
    """Casual / identity turns — hide raw reasoning in UI (model should answer directly)."""
    t = (text or "").strip()
    if not t:
        return False
    if is_casual_opening(t) or is_creator_question(t) or is_model_identity_question(t):
        return True
    if is_self_identity_question(t):
        return True
    if is_juno_internals_question(t):
        return True
    if re.search(r"你是谁|Lee是谁|李.*是谁|谁.*Lee|(juno|朱诺)\s*是谁", t, re.I):
        return True
    return False


def should_emit_reasoning_to_ui(user_message: str) -> bool:
    """Stream model reasoning into Thought panel (Cursor-style).

    Light identity/hi turns stay quiet; everything else surfaces sanitized reasoning
    when the model provides a reasoning channel (e.g. deepseek-reasoner).
    """
    if is_natural_chat_turn(user_message):
        return False
    return True


def format_ui_mode_line(mode: str) -> str:
    labels = {
        "chat": "Chat · 纯对话",
        "agent": "Agent · 可读写代码",
        "plan": "Plan · 只规划不执行",
        "ask": "Ask · 只读",
    }
    return labels.get(mode, mode)


def needs_deliberation(user_message: str, prior: list[dict] | None = None) -> bool:
    """Situational / choice / dig questions — force think-before-answer."""
    t = (user_message or "").strip()
    if not t:
        return False
    # Pure abuse must not spin Exploring / think tools
    if is_hostile_stance(t):
        return False
    if is_casual_opening(t) and not (prior or []):
        return False
    if re.search(
        r"还是|建议|该不该|要不要|怎么选|哪一个|仔细想想|再想想|再想|难道|纠结|"
        r"帮不帮|有救吗|怎么安排|是不是该|你觉得呢|值不值|划不划算|风险|"
        r"walk or drive|should I|or not|pros and cons|trade.?off",
        t,
        re.I,
    ):
        return True
    # Practical scenario with distance/time often hides goal constraints
    if re.search(
        r"(洗车|取车|送人|接人|加油|加油站|买菜|取快递|修车|轮胎|"
        r"寄件|取件|干洗|洗衣店).{0,60}(走|开|骑|坐|距离|米|m\b)",
        t,
        re.I,
    ):
        return True
    if re.search(r"(走|开|骑).{0,12}(路|车).{0,20}(还是|或者)", t):
        return True
    if re.search(r"距离.{0,20}(加油站|洗车|干洗|修车)", t):
        return True
    # Multi-constraint / plan-ish asks (Juno-style: inventory before answer)
    if re.search(
        r"怎么安排|帮我排|优先级|先做哪|约束|两难|权衡|利弊|"
        r"如果.*(还是|或者)|既要.*又要",
        t,
    ):
        return True
    tt = classify_turn_type(t, prior)
    if tt in ("design", "feedback") and prior:
        return True
    return False


def deliberation_directive(user_message: str) -> str:
    return (
        "## 【先想清楚 · 本轮强制】\n"
        "情景/多约束题：禁止秒回表面最优解。\n"
        "按 information-inventory + sequential-thinking（structured reasoning checklist）：\n"
        "1) 列出事实 / 约束 / 未知 / 成功标准（勿脑补成事实）\n"
        "2) 每条事实与约束标已用·未用；有未用项禁止终答\n"
        "3) 「大概率」=假设，写清最坏后果与低成本验证\n"
        "4) 淘汰破坏目标或硬约束的选项，再排行动顺序\n"
        "5) 用户挖坑或「再想想」→ 修订，禁止复读\n"
        "有 `think`：先调用再终答。"
    )


def build_turn_context(
    user_message: str,
    recent_messages: list[dict] | None,
    *,
    agent_mode: bool = False,
    ui_mode: str = "chat",
    session_title: str = "",
) -> str:
    """Factual turn context only — not a rulebook."""
    prior = recent_messages or []
    analysis = analyze_user_turn(
        user_message, prior, session_title=session_title, agent_mode=agent_mode,
    )
    lines: list[str] = [
        format_now_line(),
        format_ui_mode_directive(ui_mode),
        f"界面摘要：{format_ui_mode_line(ui_mode)}",
    ]
    tt = analysis.get("turn_type") or "new_task"
    label = TURN_TYPE_LABELS.get(tt, tt)
    lines.append(f"回合：{label}")
    if analysis.get("goal"):
        lines.append(f"用户此刻想要：{analysis['goal']}")
    if analysis.get("response_mode"):
        lines.append(f"该怎么回：{analysis['response_mode']}")
    if tt in ("identity", "casual"):
        lines.append(
            "纪律：本轮自己组织、最多两三句；禁止复读自我介绍，禁止复述 UI 模式/运行时配置原文。"
        )
    if analysis.get("linked_prior"):
        lines.append(f"接上文：{analysis['linked_prior'][:220]}")
    recent = summarize_recent_turns(prior, max_chars=500)
    if recent:
        lines.append(f"最近对话：{recent}")
    # peer-assistant-style relevant memory + expression (Juno HQ adapted)
    expr = expression_spine_directive(user_message, ui_mode=ui_mode)
    if expr:
        lines.append(expr)
    recalled = recall_relevant_memory(
        user_message, session_title=session_title, max_items=5 if not is_small_local_model() else 3,
    )
    if recalled:
        lines.append(recalled)
    stance = classify_user_stance(user_message)
    if stance["kind"] in ("creator_slander", "unjustified_attack"):
        lines.append(f"Stance: {stance['label']} — see abuse scene below; no scripted repeats.")
        lines.append(tone_guard_directive(user_message, intent="hostile", recent_messages=prior))
    elif stance["kind"] == "actionable_frustration" or is_user_frustrated(user_message) or is_skeptical_short_reply(user_message):
        lines.append("语气：可处理的不满 → 先认再改（一句），问具体哪点；禁止空道歉堆砌、禁止斗嘴。")
        lines.append(tone_guard_directive(user_message, intent="frustrated", recent_messages=prior))
    if ui_mode == "chat" and needs_agent_execution(user_message, prior):
        lines.append(
            "## 【Chat 禁区】\n"
            "用户要启动/跑项目/查仓库，但当前是 Chat（无工具）。\n"
            "**禁止**说「我来看看项目结构」「让我确认路径」却不动手。\n"
            "应明确：请切到界面右下/模式菜单的 **∞ Agent**，或说「已建议切 Agent」。"
        )
    if needs_deliberation(user_message, prior):
        lines.append(deliberation_directive(user_message))
    return "\n".join(lines)


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


def build_system_prompt(*, mode: str = "chat", ui_mode: str | None = None) -> str:
    """Instinct + thinking + caps + user/memory; mode + anchors LAST (highest weight)."""
    cfg = load_chat_config()
    compact = is_small_local_model(cfg)
    # mode = prompt personality (chat vs agent); ui_mode = picker truth for "你是什么模式"
    prompt_mode = "agent" if (mode or "").strip().lower() == "agent" else "chat"
    live_mode = (ui_mode or mode or "chat").strip().lower()
    if live_mode not in ("chat", "agent", "plan", "ask"):
        live_mode = prompt_mode
    instinct = load_core_instinct_inject(prompt_mode, compact=compact)
    # Prefer one thinking spine — avoid instinct + thinking + quality + chain stew
    if prompt_mode == "agent" and not compact:
        thinking = ""
        chain = load_brain_chain_inject("agent")
        quality = ""
    else:
        thinking = load_thinking_inject(prompt_mode) if not compact else ""
        chain = ""
        quality = ""
        qpath = HQ / "knowledge" / "juno-dialogue-quality.md"
        if qpath.exists() and not compact:
            qt = read_text(qpath)
            if "<!-- INJECT:quality -->" in qt:
                quality = _clip(
                    qt.split("<!-- INJECT:quality -->", 1)[1].split("<!-- END:quality -->", 1)[0].strip(),
                    900,
                )
    caps = load_capabilities_inject(prompt_mode, compact=compact)
    if caps and not compact:
        caps = _clip(caps, 1200 if prompt_mode == "chat" else 1600)
    user_block = _clip(read_text(USER), 600) if compact else _clip(read_text(USER), 1200)
    # Always-on spine only — full MEMORY dump replaced by per-turn recall_relevant_memory
    memory_block = load_memory_core_always(compact=compact)
    anchors = load_dialogue_anchors(prompt_mode)
    if anchors:
        anchors = _clip(anchors, 900 if compact else 1400)
    owner = owner_display_name()

    parts = [
        f"你是 **Juno**，{owner} 的私人 AI 助手。"
        "闲聊靠自己想；干活时可用能力辅助（搜集信息、拆问题、改代码）抬高上限——"
        "那是方法，不是要背给用户听的稿。",
        "",
        instinct,
    ]
    if thinking.strip():
        parts.extend(["", thinking.strip()])
    if quality.strip():
        parts.extend(["", quality.strip()])
    if caps.strip():
        parts.extend(["", caps.strip()])
    if chain.strip():
        parts.extend(["", _clip(chain.strip(), 1800)])
    if user_block.strip():
        parts.extend(["", "## 关于你", user_block.strip()])
    if memory_block.strip():
        parts.extend(["", memory_block.strip()])
    if anchors.strip():
        parts.extend(["", anchors.strip()])
    parts.extend(["", format_ui_mode_directive(live_mode)])
    return "\n".join(parts)


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
    """cloud API thinking models require reasoning_content on tool-call turns."""
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


def pick_max_tokens(user_message: str, cfg: dict) -> int:
    base = int(cfg.get("max_tokens") or 4096)
    if is_self_identity_question(user_message) or is_casual_opening(user_message):
        return min(base, 480)
    if is_mode_question(user_message) or is_model_identity_question(user_message):
        return min(base, 640)
    return base


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
        "max_tokens": pick_max_tokens(user_message, cfg),
        "temperature": pick_temperature(user_message, cfg),
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


def _validate_ready(cfg: dict) -> None:
    if is_cursor_agent(cfg):
        import juno_cursor_agent
        st = juno_cursor_agent.check_agent()
        if not st.get("ok"):
            raise RuntimeError(st.get("detail") or "Cursor Agent 未登录或不可用。请运行：agent login")
        return
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
        raise RuntimeError("API key missing. Set a cloud API key in settings, or switch to local Ollama.")


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
    emit_reasoning = should_emit_reasoning_to_ui(user_message)
    tools_pending_emitted = False

    with _http_post_stream(_api_url(cfg), payload, api_key) as resp:
        dec = _Utf8StreamDecoder()
        buf = ""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                buf += dec.finish()
                break
            buf += dec.feed(chunk)
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
                    if emit_reasoning:
                        clean = sanitize_reasoning_chunk(part)
                        if clean:
                            yield {"kind": "reasoning_delta", "text": clean}
                tcs = delta.get("tool_calls") or []
                if tcs and not tools_pending_emitted:
                    tools_pending_emitted = True
                    yield {"kind": "tools_pending"}
                if delta.get("content"):
                    content_parts.append(delta["content"])
                    # Final-answer tokens only (skip content when this step is a tool call)
                    if not tools_pending_emitted:
                        yield {"kind": "delta", "text": delta["content"]}
                for tc in tcs:
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
        "reasoning_content": "".join(reasoning_parts).replace("\ufffd", ""),
        "tool_calls": tool_calls,
    }


def chat_complete(
    messages: list[dict],
    *,
    user_message: str = "",
    cursor_cli_mode: str | None = None,
) -> tuple[str, dict]:
    cfg = load_chat_config()
    _validate_ready(cfg)
    if is_cursor_agent(cfg):
        import juno_cursor_agent
        ws = HQ / str(cfg.get("workspace") or ".").lstrip("/\\")
        return juno_cursor_agent.chat_complete(
            messages, user_message=user_message, workspace=ws.resolve(), cli_mode=cursor_cli_mode
        )

    api_key = get_api_key(cfg) if not is_ollama(cfg) else None

    payload = _request_payload(cfg, messages, stream=False, user_message=user_message)
    with _http_post_stream(_api_url(cfg), payload, api_key) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"API 返回异常: {data}") from e
    return content, data.get("usage") or {}


def chat_stream(
    messages: list[dict],
    *,
    user_message: str = "",
    cursor_cli_mode: str | None = None,
) -> Generator[str, None, None]:
    cfg = load_chat_config()
    _validate_ready(cfg)
    if is_cursor_agent(cfg):
        import juno_cursor_agent
        ws = HQ / str(cfg.get("workspace") or ".").lstrip("/\\")
        yield from juno_cursor_agent.chat_stream(
            messages, user_message=user_message, workspace=ws.resolve(), cli_mode=cursor_cli_mode
        )
        return

    api_key = get_api_key(cfg) if not is_ollama(cfg) else None

    payload = _request_payload(cfg, messages, stream=True, user_message=user_message)
    with _http_post_stream(_api_url(cfg), payload, api_key) as resp:
        dec = _Utf8StreamDecoder()
        buf = ""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                buf += dec.finish()
                break
            buf += dec.feed(chunk)
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
                    yield delta.replace("\ufffd", "")


def chat_status() -> dict:
    cfg = load_chat_config()
    provider = cfg.get("provider", "ollama")
    policy = agent_backend_policy(cfg)
    resolved = resolve_agent_backend(cfg)
    if is_agent_cursor_backend(cfg) or is_cursor_agent(cfg):
        import juno_cursor_agent
        st = juno_cursor_agent.check_agent()
        base = {
            "has_local_config": CHAT_LOCAL.exists(),
            "agent_backend": resolved,
            "agent_backend_policy": policy,
            "cursor_agent_detail": st.get("detail"),
        }
        if is_cursor_agent(cfg):
            return {
                **base,
                "configured": bool(st.get("ok")),
                "provider": "cursor_agent",
                "mode": "cursor",
                "mode_label": "Cursor Agent（全走 CLI）",
                "model": cfg.get("model") or "cursor-agent",
                "api_base": "cursor-cli",
                "ollama_running": False,
                "ollama_models": [],
                "hint": None if st.get("ok") else (st.get("detail") or "请 agent login"),
                "prompt_mode": "full",
            }
        # hybrid: chat via provider, agent via cursor
        if is_ollama(cfg):
            ost = check_ollama(cfg)
            chat_be = cfg.get("chat_backend") or ""
            label = "Chat Cursor · Agent Cursor" if chat_be == "cursor_agent" else "Chat 本地 · Agent Cursor"
            return {
                **base,
                "configured": ost["running"] and bool(st.get("ok")),
                "provider": "ollama",
                "mode": "hybrid",
                "mode_label": label,
                "chat_backend": chat_be,
                "model": cfg.get("model"),
                "api_base": ost["base"],
                "ollama_running": ost["running"],
                "ollama_models": ost.get("models") or [],
                "hint": None if ost["running"] and st.get("ok") else "Chat 需 Ollama；Agent 需 Cursor 登录",
                "prompt_mode": "compact" if is_small_local_model(cfg) else "full",
            }
        key = get_api_key(cfg)
        return {
            **base,
            "configured": bool(key) and bool(st.get("ok")),
            "provider": provider,
            "mode": "hybrid",
            "mode_label": f"权威 · Chat {provider} · Agent Cursor CLI",
            "model": cfg.get("model"),
            "api_base": cfg.get("api_base"),
            "ollama_running": False,
            "ollama_models": [],
            "hint": None if key and st.get("ok") else "配置 Chat API key；Agent 需 Cursor CLI（agent login）",
            "prompt_mode": cfg.get("prompt_mode") or "full",
        }
    if is_ollama(cfg):
        st = check_ollama(cfg)
        agent_hint = (
            " · Agent Cursor" if resolved == "cursor_agent"
            else (" · Agent 内置" if policy != "auto" else " · Agent auto→内置(Cursor 未就绪)")
        )
        return {
            "configured": st["running"],
            "provider": "ollama",
            "mode": "local" if resolved == "builtin" else "hybrid",
            "mode_label": ("本地" if resolved == "builtin" else "权威") + agent_hint,
            "model": cfg.get("model"),
            "api_base": st["base"],
            "ollama_running": st["running"],
            "ollama_models": st.get("models") or [],
            "has_local_config": CHAT_LOCAL.exists(),
            "agent_backend": resolved,
            "agent_backend_policy": policy,
            "hint": None if st["running"] else "请安装并启动 Ollama，然后 ollama pull qwen2.5:7b",
            "prompt_mode": "compact" if is_small_local_model(cfg) else "full",
        }
    key = get_api_key(cfg)
    agent_hint = (
        " · Agent Cursor CLI" if resolved == "cursor_agent"
        else (" · Agent 内置" if policy == "builtin" else " · Agent auto→内置(Cursor 未就绪)")
    )
    return {
        "configured": bool(key),
        "provider": "openai_compatible",
        "mode": "hybrid" if resolved == "cursor_agent" else "cloud",
        "mode_label": ("权威 · Chat API" if resolved == "cursor_agent" else "云端 API") + agent_hint,
        "model": cfg.get("model"),
        "api_base": cfg.get("api_base"),
        "ollama_running": False,
        "ollama_models": [],
        "has_local_config": CHAT_LOCAL.exists(),
        "agent_backend": resolved,
        "agent_backend_policy": policy,
        "hint": None if key else "请填写 API Key，或切换为本地 Ollama",
        "prompt_mode": "compact" if is_small_local_model(cfg) else "full",
    }
