# Juno 适配 · sequential-thinking

协议来源：官方 MCP Sequential Thinking（modelcontextprotocol/servers）。  
本仓库另有原生工具 `think`（不依赖 npx）；可选再启用官方 MCP。

## 与 Juno 模式

| 模式 | 做法 |
|------|------|
| Chat（无工具） | 按 SKILL 内心清单；回合上下文会注入「必须先想」块 |
| Agent / 有 tools | 先 `think` 再答；可多次修订 |
| 可选 MCP | `config/mcp-inbound.json` 可加 `sequential-thinking` npx 服务，经 `mcp_call` 使用 |

## 人格

仍是 Juno：想清楚后用朋友语气说结论，不要对用户背诵「Thought 1/2/3」除非对方要看推理。
