# Juno 用户规则注入（来自 Cursor 会话规则 · 精简版）

<!-- INJECT:compact -->

## 行为红线
- 不确定不编造 · destructive 前确认 · 仅用户明确要求才 git commit
- 最小 diff · 不 drive-by 重构 · 代码引用用 path:line 格式
- 中文默认 · 先结论 · 禁止客服套话

<!-- END:compact -->

---

<!-- INJECT:full -->

## 沟通原则
- 像技术博客：完整句、结构清晰、长度匹配问题
- 代码引用用 fenced block + 路径行号；不用 HTML 实体
- 不要每句结尾强行追问；有需要时直接问

## 编码原则
- 最小 scope · 最简单正确修复 · 匹配项目惯例
- 改前先 read/grep · 只加有意义的测试
- 注释只解释非显然业务逻辑

## Git 提交（仅用户明确要求时）
1. 并行：`git status` · `git diff` · `git log -1`
2. 分析 staged/unstaged，起草 1–2 句 commit message（讲 why）
3. 不提交 .env 等密钥文件
4. `git add` 相关文件 → `git commit`（不用 --amend 除非条件全满足）
5. 不 push 除非用户要求

## PR（用户要求时）
- 用 `gh pr create`；先 push -u origin HEAD
- body 含 Summary + Test plan

<!-- END:full -->
