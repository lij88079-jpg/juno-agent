# Juno 适配 · pdf

来源：[anthropics/skills](https://github.com/anthropics/skills) · 官方正文见 `SKILL.md`。

## 本仓库约定

- 输入文件：用户给出的路径，或 `knowledge/`、`uploads/`、`.tmp/`
- 输出：默认 `.tmp/` 或用户指定；重要成品可再移到 `knowledge/`
- 缺 Python 库（如 pypdf、pdf2image）时先列安装命令，再执行
- 涉及隐私/密钥内容的 PDF：不外传、不写进公开记忆，除非用户明确要求
