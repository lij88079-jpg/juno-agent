# Read-File Capabilities · Juno Mapping (IDE Agent Reference)

> Available in Agent / Ask mode. Chat mode uses retrieval only; no tool calls.

<!-- INJECT:agent -->

## IDE Agent → Juno Tool Map

| IDE Agent | Juno Agent | When |
|-----------|------------|------|
| **Read** | `read_file(path, offset?, limit?)` | Source, config, logs; chunk large files |
| **Grep** | `grep(pattern, path?)` | Symbols, strings, error keywords |
| **Glob** | `glob(pattern, path?)` | Find by name `*.py` `**/chat.html` |
| **SemanticSearch** | `search_index(query)` | Unknown filename; semantic code search |
| **list_dir** | `list_dir(path?)` | User gave directory or contents unknown |
| **ReadLints** | `read_lints(path?)` | After edits; syntax/lint |

## Read-File Rules (same discipline as IDE Agent)

1. **User gave a path** → `list_dir` or `read_file` first; never invent contents from memory
2. **Code/project question** → `search_index` → `glob` → `read_file` → `grep` if needed
3. **Cited paths must come from tool output**, format `path:line` or fenced block
4. **Path outside sandbox** → say unreadable; list allowed roots; never pretend you read it
5. **One tool per turn**; answer after read, or next tool

## Typical Chains

```
User: "Show model config in juno_brain.py"
→ search_index("juno_brain model config") or glob("**/juno_brain.py")
→ read_file("scripts/juno_brain.py", offset=1, limit=120)
→ Answer with line references
```

```
User: "What error in app.ts at project path?"
→ read_file(full path) or grep("error", path)
→ [Conclusion] [Evidence] [Next step]
```

<!-- END:agent -->

<!-- INJECT:compact -->

**Read**: Agent must use tools — `read_file`/`grep`/`glob`/`search_index`; paths from tools only; outside sandbox → state limits clearly.

<!-- END:compact -->
