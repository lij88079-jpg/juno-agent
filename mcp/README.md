# Juno MCP Server

在 Cursor 中注册（Settings → MCP → Add）：

```json
{
  "juno": {
    "command": "python",
    "args": ["mcp/juno_server.py"],
    "cwd": "/path/to/juno-agent"
  }
}
```

将 `cwd` 改为本仓库根目录的绝对路径。

## Tools

- `juno_search_memory` — 混合语义检索 Juno 索引
- `juno_read_memory` — 读取 MEMORY.md
- `juno_ide_context` — 读取 IDE 上下文（需先 POST `/api/context/open-files`）
