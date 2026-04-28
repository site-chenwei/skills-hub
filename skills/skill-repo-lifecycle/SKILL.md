---
name: skill-repo-lifecycle
description: "Use when maintaining a repository of Codex skills, especially skills-hub: adding or updating Skill folders, keeping SKILL.md/run.py/scripts/tests/agents metadata consistent, running aggregate skill tests, downshifting user-level AGENTS rules into skills, and synchronizing repo-owned skills to a local runtime install directory with parity and smoke checks."
---

# Skill 仓库生命周期

用于维护本仓库这类 repo-owned Skill 集合：确认 Skill 边界、补齐脚本和测试、维护用户级 AGENTS 下沉边界，并把源码态变更同步到运行态安装副本。

## 运行约定

- 先把 `<skill_root>` 设为当前已打开 `SKILL.md` 的所在目录。
- 所有辅助脚本统一通过 `<python_cmd> <skill_root>/run.py ...` 调用，不要手拼 `scripts/*.py` 的绝对路径。
- 其中 `<python_cmd>` 表示当前环境可用的 Python 启动命令：Windows / PowerShell 优先 `py -3`，其次 `python`，最后 `python3`；类 Unix 环境优先 `python3`，其次 `python`。
- `<skill_root>` 只能由本次实际打开的 `SKILL.md` 路径推导；不要根据 Skill 名称、同名目录、`.system`、`builtin`、`installed` 等目录习惯切换到其他路径。
- 调用 `run.py`、`scripts/`、`references/`、模板或其他附件前，先在 `<skill_root>` 下显式确认目标存在；不存在时报告附件缺失并回退手工流程。
- 对用户说明使用本 Skill 时，区分已确认入口文件、推导出的根目录和已检查存在的附件。

## 工作流

1. 先扫描 Skill 仓库事实。
   - 优先执行 `<python_cmd> <skill_root>/run.py lifecycle-scope --repo <repo> --format markdown`
   - 确认 `skills/*/SKILL.md` 清单、每个 Skill 的 `run.py`、`agents/openai.yaml`、测试目录、参考资料和脚本目录状态。
2. 维护 Skill 内容。
   - 新增 Skill 时保持 `SKILL.md`、`agents/openai.yaml`、`run.py`、必要 `scripts/` 或 `references/`、以及单测一起落地。
   - 更新 `SKILL.md` 的触发描述后，检查 `agents/openai.yaml` 是否仍匹配。
   - 高风险或确定性流程优先沉淀为脚本；只把可变判断留在 `SKILL.md` 或 reference。
3. 维护用户级 AGENTS 边界。
   - 用户级 AGENTS 只保留全局规则：语言、最小改动、安全边界、非破坏性 Git、沟通交付、检索优先级。
   - Harmony、DocsHub、结构化开发、具体运行路径、附件检查、验证矩阵等专门流程应下沉到对应 Skill。
   - 修改仓库外 `/Users/bill/.codex/AGENTS.md` 前，先确认真实路径和作用边界；不要把仓库 `git status` 干净误解成没有改外部文件。
4. 验证源码态。
   - 本仓库主验证入口是 `<python_cmd> -m unittest skills.test_all_skills`。
   - 需要复核发现范围时，补跑 `<python_cmd> -m unittest discover -s skills -p 'test_*.py'`。
   - 不要把仓库根目录的 `<python_cmd> -m unittest discover` 当成成功信号。
5. 同步运行态安装副本。
   - 只有用户要求同步、交付 repo-owned Skill 改造，或需要验证实际运行副本时才同步。
   - 默认安装目录是 `/Users/bill/.cc-switch/skills`；只覆盖本仓库拥有的同名 Skill，不删除其他已安装 Skill。
   - 推荐目录级同步：`rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' --exclude '.pytest_cache/' skills/<skill>/ /Users/bill/.cc-switch/skills/<skill>/`
   - 同步后用 `diff -qr` 或 checksum dry-run 做 parity check，再跑安装态 `run.py --help` 和关键子命令 smoke。

## 入口脚本

- `<skill_root>/run.py lifecycle-scope`
  - 输出 repo-owned Skill 清单、缺失附件、聚合测试入口、安装目录状态和源码/安装副本一致性提示。
  - 对源码存在但安装副本缺失、安装副本与源码不一致、`run.py` 缺少测试覆盖等情况输出 attention。
  - 支持 `--install-root <path>` 和 `--format markdown|json`。

## 参考

- 需要完整维护清单时，读取 [references/lifecycle-checklist.md](references/lifecycle-checklist.md)。
