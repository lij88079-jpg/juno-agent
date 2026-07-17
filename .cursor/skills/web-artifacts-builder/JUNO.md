# Juno 适配 · web-artifacts-builder

来源：[anthropics/skills](https://github.com/anthropics/skills) · 官方正文见 `SKILL.md`。

## 路径与产品语境

- 官方文案里的「claude.ai artifacts」→ 在本仓库理解为 **可单文件打开的前端产物**
- 初始化/打包脚本：本 skill 目录下 `scripts/init-artifact.sh`、`bundle-artifact.sh`
- 产出目录优先：`training/artifacts/` 或用户指定路径（创建前先确认）
- 简单静态页不必硬上本 skill → 可走 `frontend-design`；复杂 React/多组件再用本流程
