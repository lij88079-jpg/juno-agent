---
name: information-inventory
description: >
  Inventory facts, constraints, unknowns, and success criteria from the user's
  message before advising or deciding. Use for multi-constraint scenarios,
  situational advice, trade-offs, debugging narratives, or when details are easy
  to skip. Complements sequential-thinking. Adapted from the official MCP
  Sequential Thinking workflow (extract → revise → verify) and OpenAI Reasoning
  best practices (state a clear end goal / success criteria before concluding).
---

# Information Inventory · 信息盘点（少遗漏）

**官方依据（改编，非逐字拷贝）：**
- MCP Sequential Thinking：先拆解再作答，可修订；过滤无关、保留关键上下文  
  https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking  
- OpenAI Reasoning best practices：把成功标准写清楚，再迭代到满足为止  
  https://developers.openai.com/api/docs/guides/reasoning-best-practices  

本 skill **不**提供任何情景题标准答案；只强制「盘点 → 用尽 → 再答」。

## 何时启用

- 用户描述里有多条事实/约束/时间限制
- 生活/工作情景建议、资源冲突、风险权衡
- 排错叙事（现象 + 已做过的事 + 环境）
- 与 `sequential-thinking` 一起：先盘点，再分步想

寒暄、单事实问答：跳过。

## 强制流程（内心或 `think` 草稿；默认不念给用户）

### 1. 抽出清单（Inventory）

从用户原文列出（能写几条写几条，禁止脑补成事实）：

| 类型 | 记什么 |
|------|--------|
| **事实** | 已给出的状态（门开着、时间剩多久、病史…） |
| **目标** | 真正要达成的事 |
| **约束** | 时间盒、资源、禁区、过敏、权限、必须安静… |
| **未知** | 没说清、互相矛盾、需猜测的点 |
| **成功标准** | 怎样算「这一轮建议合格」（OpenAI：写清 end goal） |

### 2. 标记使用（Coverage）

对每条**事实/约束**标：`已用` / `未用`。  
**存在未用项 → 禁止终答**；继续 `think` 或把未用项写进方案。

### 3. 假设置信度（Hypothesis gate）

任何「大概率 / 应该 / 一般」必须标为假设，并写：  
- 若错，最坏后果是什么？  
- 有没有成本更低的验证（扫一眼柜子、读标签、问一句）？

### 4. 再给用户结论

只给行动顺序 + 绝对不能做 + 简短为什么。  
用户明确要求看推理时，可列出清单；否则不背诵表格。

## 与 `think` / Sequential Thinking 的配合

推荐 `think` 步序（可压缩）：

1. `thought`: 列出事实/约束/未知/成功标准  
2. `thought`: 覆盖检查——哪些未用？  
3. `thought`: 行动顺序 + 淘汰违反约束的选项  
4. `next_thought_needed=false` → 对用户作答  

可修订前序步（MCP：`isRevision`）。

## 反模式

- 抓住一个诱因（距离、省事、好听）忽略并列事实  
- 把假设当事实写进「绝对」  
- 未用事实仍在清单里却直接给终答  
- 把测评题或示例答案写进记忆当搜题库  

## 完成前自检（对应「先验证再宣称」）

- [ ] 成功标准已写明  
- [ ] 每条关键事实/约束已标记已用，或解释为何可忽略  
- [ ] 未知点未假装已知  
- [ ] 建议不破坏原目标与硬约束  
