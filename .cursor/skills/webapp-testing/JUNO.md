# Juno 适配 · webapp-testing

来源：[anthropics/skills](https://github.com/anthropics/skills) · 官方正文见 `SKILL.md`。

## 本仓库默认对象

- Juno 聊天 / 训练台：本地 `http://127.0.0.1:8765/chat`、`/studio`（以用户当前配置为准）
- 先确认服务是否已在跑；未启动时用本 skill 的 `scripts/with_server.py` 或仓库里的启动脚本
- 截图与临时产物优先放 `.tmp/` 或用户指定路径，勿写入 `memory/` 敏感目录
- 依赖：本机需能跑 Playwright（缺依赖时先说明安装步骤，再写测试脚本）
