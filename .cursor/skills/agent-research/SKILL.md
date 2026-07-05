---
name: agent-research
description: Research, explain concepts, summarize documents, compare options. Use when user needs 调研、学习、总结、是什么、为什么、对比分析, or @agent-research.
user-invocable: true
allowed-tools: Read, Write, Grep, Glob, WebSearch, WebFetch
---

# Agent Research · 调研与学习

## Workflow

1. Clarify topic and depth (quick vs detailed)
2. Check `knowledge/` and user-attached files **first**
3. Use web search only when local knowledge is insufficient and user would benefit
4. Structure output: **结论 → 要点 → 来源/依据**

## Output format (default)

```markdown
## 结论（一句话）

## 要点
- ...

## 说明（可选展开）

## 参考
- 本地：文件名
- 外部：链接（如有）
```

## Rules

- Distinguish fact vs inference
- Say when information may be outdated
- Bilingual if USER.md prefers 中英对照 for learning topics
