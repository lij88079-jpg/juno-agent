---
name: sequential-thinking
description: >
  Structured multi-step reasoning before answering. Use when the user asks for advice,
  choices (A or B), situational judgment, debugging, design trade-offs, or says
  "再想想/仔细想想", or whenever jumping to a conclusion risks looking careless.
  Inspired by the official Model Context Protocol Sequential Thinking server.
  Prefer the native `think` tool when available; otherwise run the checklist mentally
  (do not dump the whole checklist to the user).
---

# Sequential Thinking · 分步想清楚再答

改编自官方 MCP：[`@modelcontextprotocol/server-sequential-thinking`](https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking)。  
可选·可修订。**与 `information-inventory` 联用**：先盘点事实/约束，再分步推理。

## 何时必须启用

- 二选一 / 出行 / 生活建议（「走路还是开车」「该不该…」）
- 多约束、目标可能互相打架
- 用户挖坑、反问、说「再想想」
- 架构权衡、排错、方案对比

**不必**用：寒暄、查一个已知事实、纯执行已明确的一步。

## 工具优先：`think`

若当前模式有 `think` 工具，先调用再开口（可多次）：

| 参数 | 含义 |
|------|------|
| `thought` | 本步在想什么 |
| `thought_number` | 第几步（从 1） |
| `total_thoughts` | 预估总步数（可中途改） |
| `next_thought_needed` | 是否还要再想一步 |
| `is_revision` | 是否在推翻前序结论 |
| `revises_thought` | 在修订第几步（可选） |

循环到 `next_thought_needed=false`，再对用户给结论。

## 无工具时的内心清单（不输出中间过程）

至少过完再答：

1. **目标**：用户真正要完成什么？  
2. **隐含条件**：要带什么东西/人？不做这件事目标还成不成立？  
3. **选项淘汰**：哪个选项会让目标破产？先杀掉  
4. **表面诱因**：距离、省时间、省油——只能在目标成立后比较  
5. **压力测试**：用户若反问「难道…？」我的结论是否还站得住？  
6. **结论**：一句话 + 必要理由；若刚才错了就改口

## 修订规则

- 发现前序假设错了 → 标修订，换结论；禁止复读同一套错理由  
- 不确定 → 标出来，或只问一个关键澄清问题  

## 对用户可见的输出

默认只给**最终结论**（简洁）。  
用户明确要求「展示推理过程」时，才给短步骤。
