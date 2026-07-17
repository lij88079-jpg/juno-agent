# Juno 适配 · skill-creator

来源：[anthropics/skills](https://github.com/anthropics/skills) · 官方正文见 `SKILL.md`。

## 落盘位置（覆盖官方「随便放」的指引）

- 新 skill → `./.cursor/skills/<name>/SKILL.md`
- 需要 Juno 窗口也能路由 → 在 `config/cc-skills.json` 的 `imports` 加一条（id / intents / keywords）
- 若要用 `@skill-name` 显式调用 → 同步扩展 `scripts/juno_skills.py` 的 `EXPLICIT_SKILL_RE` 与 `CC_SKILL_CLIP`
- 可选：同目录写 `JUNO.md`（本文件同类）做仓库专属覆盖，**不要改写**官方 SKILL 正文

## 人格与语言

- 对外仍是 **Juno**；按 `USER.md` / `SOUL.md` / 本能回复
- 默认中文说明；用户用英文时跟用户语言
- Eval / benchmark 脚本在 skill 目录 `scripts/`；环境不具备时先交付可用的 `SKILL.md`，再说明如何补测
