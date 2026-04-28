---
name: git-delivery
description: "Use when the user asks to stage, commit, push, publish, close out, or deliver repository changes. Focus on safe Git handoff: inspect the full worktree, separate source changes from generated/system/diagnostic artifacts, run lightweight integrity checks, verify branch/upstream state, and re-check local and remote sync after commit or push."
---

# Git 交付闭环

用于把代码改动安全交付到 Git：先确认工作区事实，再决定 stage/commit/push 的边界，最后用证据确认本地和远端状态。

## 运行约定

- 先把 `<skill_root>` 设为当前已打开 `SKILL.md` 的所在目录。
- 所有辅助脚本统一通过 `<python_cmd> <skill_root>/run.py ...` 调用，不要手拼 `scripts/*.py` 的绝对路径。
- 其中 `<python_cmd>` 表示当前环境可用的 Python 启动命令：Windows / PowerShell 优先 `py -3`，其次 `python`，最后 `python3`；类 Unix 环境优先 `python3`，其次 `python`。
- `<skill_root>` 只能由本次实际打开的 `SKILL.md` 路径推导；不要根据 Skill 名称、同名目录、`.system`、`builtin`、`installed` 等目录习惯切换到其他路径。
- 调用 `run.py`、`scripts/`、`references/`、模板或其他附件前，先在 `<skill_root>` 下显式确认目标存在；不存在时报告附件缺失并回退手工流程。
- 对用户说明使用本 Skill 时，区分已确认入口文件、推导出的根目录和已检查存在的附件。

## 工作流

1. 先收敛交付范围。
   - 优先执行 `<python_cmd> <skill_root>/run.py preflight --repo <repo> --format markdown`
   - 需要兼容旧调用时，可执行 `<python_cmd> <skill_root>/run.py delivery-scope --repo <repo> --format markdown`
   - 读取 `git status --short --branch`、当前分支、upstream、ahead/behind、未跟踪文件和轻量风险提示。
   - 如果上一轮提交、推送或工具调用被中断，必须从这一步重新开始，不沿用旧 stage/push 假设。
2. 区分可交付改动和本地产物。
   - 优先执行 `<python_cmd> <skill_root>/run.py stage-plan --repo <repo> --format markdown` 生成只读 stage 建议。
   - 默认排除 `.DS_Store`、`Thumbs.db`、`appfreeze-*`、HiLog/crash/trace 日志、构建缓存、临时导出和大体积诊断文件。
   - `.env`、密钥、证书、token、凭据文件一律视为阻塞风险，除非用户明确说明并且内容已安全处理。
   - 构建工具生成的副作用文件要先确认是否应提交；Harmony 项目里的 `BuildProfile.ets` 这类生成物通常先回滚或排除。
3. 提交前做最小完整性检查。
   - 至少运行 `git diff --check`；有 staged diff 时也检查 `git diff --cached --check`。
   - 已经 stage 后执行 `<python_cmd> <skill_root>/run.py commit-plan --repo <repo> --format markdown`，只读检查 staged diff、diffstat 和建议提交信息。
   - 按仓库类型补最小验证：代码仓跑受影响测试/构建，文档内容仓可用 JSON/Markdown/敏感信息检查替代完整构建。
4. 执行 Git 操作。
   - 只 stage 本次应交付的文件；不要用宽泛 `git add .` 混入未确认产物。
   - commit message 默认使用简体中文，描述真实改动，不夸大验证范围。
   - push 前确认 upstream 和 ahead/behind；无 upstream 时不要猜远端目标。
5. 交付后复核。
   - 重新执行 `git status --short --branch`。
   - push 后用 `<python_cmd> <skill_root>/run.py post-push-check --repo <repo> --expected-branch <branch> --expected-commit <commit>` 或等价命令确认本地与 upstream 同步。
   - 最终回答保留分支、提交、验证命令和仍保留的未跟踪本地产物。

## 入口脚本

- `<skill_root>/run.py preflight`
  - 输出交付前门禁结果，包含 stable JSON 的 `schema_version`、`checks`、`blockers`、`warnings` 和摘要。
- `<skill_root>/run.py delivery-scope`
  - 输出仓库路径、分支、upstream、ahead/behind、状态分类、轻量风险提示和 `git diff --check` 结果。
  - 支持 `--format markdown|json`。
- `<skill_root>/run.py stage-plan`
  - 只读输出每个变更文件的建议动作：`stage`、`needs-review`、`exclude` 或 `block`；不会修改 index。
- `<skill_root>/run.py commit-plan`
  - 只读检查 staged diff，输出 staged 文件、diffstat、建议提交信息、blockers 和验证提示；不会创建提交。
- `<skill_root>/run.py post-push-check`
  - 检查当前分支、upstream、ahead/behind 和可选 expected commit 是否已进入 upstream。

## 参考

- 需要更细的提交前/推送后清单时，读取 [references/delivery-checklist.md](references/delivery-checklist.md)。
