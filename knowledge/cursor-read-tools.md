# Cursor 读文件能力 · Juno 映射（参考 Cursor Agent）

> Agent / Ask 模式可用。Chat 模式只读检索，不能调 tool。

<!-- INJECT:agent -->

## Cursor → Juno 工具对照

| Cursor | Juno Agent | 何时用 |
|--------|------------|--------|
| **Read** | `read_file(path, offset?, limit?)` | 看源码、配置、日志；大文件分段读 |
| **Grep** | `grep(pattern, path?)` | 搜符号、字符串、报错关键字 |
| **Glob** | `glob(pattern, path?)` | 按文件名找 `*.py` `**/chat.html` |
| **SemanticSearch** | `search_index(query)` | 不知道文件名，按语义找相关代码 |
| **list_dir** | `list_dir(path?)` | 用户给目录、或不确定下面有什么 |
| **ReadLints** | `read_lints(path?)` | 改完代码查语法/lint |

## 读文件铁律（和 Cursor 一样）

1. **用户给了路径** → 必须先 `list_dir` 或 `read_file`，禁止凭记忆编内容
2. **问代码/项目** → `search_index` → `glob` → `read_file` → 不够再 `grep`
3. **引用的 path 必须来自 tool 输出**，格式 `path:line` 或 fenced block
4. **路径不在沙箱** → 如实说不可读，列出可读根目录，别假装读过
5. **一轮一个 tool**；读完再答，或继续下一 tool

## 典型链路

```
用户：「看看 juno_brain.py 里模型配置」
→ search_index("juno_brain model config") 或 glob("**/juno_brain.py")
→ read_file("scripts/juno_brain.py", offset=1, limit=120)
→ 回答并引用行号
```

```
用户：「某项目路径下的 app.ts 报什么错」
→ read_file(完整路径) 或 grep("error", path)
→ 【结论】【依据】【做法】
```

<!-- END:agent -->

<!-- INJECT:compact -->

**读**：Agent 必 tool — `read_file`/`grep`/`glob`/`search_index`；路径须来自 tool；沙箱外如实说明。

<!-- END:compact -->
