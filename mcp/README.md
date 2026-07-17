# Juno MCP Server

Register in your IDE (Settings → MCP → Add):

```json
{
  "juno": {
    "command": "python",
    "args": ["mcp/juno_server.py"],
    "cwd": "/path/to/juno-agent"
  }
}
```

Set `cwd` to this repository's absolute path.

## Tools

- `juno_search_memory` — Hybrid semantic search on Juno index
- `juno_read_memory` — Read MEMORY.md
- `juno_ide_context` — Read IDE context (requires prior POST `/api/context/open-files`)
