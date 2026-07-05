# Juno MCP Server

在 Cursor 中注册（Settings → MCP → Add）：

```json
{
  "juno": {
    "command": "python",
    "args": ["C:\\Users\\solut xc\\Desktop\\my-ai-agent\\mcp\\juno_server.py"]
  }
}
```

## Tools

- `juno_search_memory` — 混合语义检索 Juno 索引
- `juno_read_memory` — 读取 MEMORY.md
- `juno_ide_context` — 读取 IDE 上下文（需先 POST `/api/context/open-files`）
