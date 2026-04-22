# skills-hub

个人通用 Skill 仓库，统一存放可复用的 `SKILL.md` 工作流、检查清单和配套辅助脚本。

## 当前 Skill

- `harmony-build`
- `docs-hub`
- `project-onboarding`
- `structured-dev`
- `code-review-checklist`
- `verification-and-debug`

## 新增能力形态

- `project-onboarding`：支持仓库事实扫描，自动抽取文档入口、技术栈信号和验证命令候选
- `structured-dev`：支持变更简报生成，按路径和风险信号给出 light / full 工作流
- `code-review-checklist`：支持变更范围分析，输出文件分类、风险标签和测试缺口
- `verification-and-debug`：支持失败命令捕获，统一记录退出码、日志尾部和故障分类
- `harmony-build`：支持 Windows 侧 Harmony 构建环境探测、缓存基线和 hvigor 验证
- `docs-hub`：支持外部 DocsHub 根目录初始化、本地索引构建与文档检索；Skill bundle 本身不携带文档快照

## 仓库布局

所有 Skill 均位于 `skills/` 目录下；需要 deterministic 能力时，优先把脚本放进各自 Skill 的 `scripts/`，并在 Skill 根目录暴露统一的 `run.py` 入口。调用时先取当前已打开 `SKILL.md` 的所在目录作为 `<skill_root>`，再执行 `<python_cmd> <skill_root>/run.py ...`，不要手拼 `scripts/*.py` 的安装绝对路径。其中 `<python_cmd>` 表示当前环境可用的 Python 启动命令：Windows / PowerShell 优先 `py -3`，其次 `python`，最后 `python3`；类 Unix 环境优先 `python3`，其次 `python`。

## 使用 CC Switch 安装

在 `Skills -> Repository Management -> Add Repository` 中添加自定义仓库：

- Owner: `<your-github-owner>`
- Name: `skills-hub`
- Branch: `main`
- Subdirectory: `skills`

也可以直接填写仓库 URL：

```text
https://github.com/<your-github-owner>/skills-hub/tree/main/skills
```

添加完成后刷新列表，再安装需要的 Skill。

## 直接本地使用

如果只想在本机测试，可将单个 Skill 软链接或复制到目标目录，例如：

- Codex: `~/.codex/skills/<skill-name>`
- Claude Code: `~/.claude/skills/<skill-name>`
- Gemini CLI: `~/.gemini/skills/<skill-name>`
