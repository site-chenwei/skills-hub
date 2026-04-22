---
name: structured-dev
description: Use this skill for new features, refactors, multi-file or high-risk changes, interface or schema changes, dependency upgrades, and performance/security/stability work. Trigger it when the user asks for a plan first, requests a structured workflow, or needs explicit workflow depth and validation gates.
---

# 结构化开发

在复杂任务里，按“研究与分析 -> 方案构思 -> 代码开发 -> 复查 -> 编译与验证”的顺序推进，减少拍脑袋决策和散乱改动。

## 运行约定

- 先把 `<skill_root>` 设为当前已打开 `SKILL.md` 的所在目录。
- 所有辅助脚本统一通过 `<python_cmd> <skill_root>/run.py ...` 调用，不要手拼 `scripts/*.py` 的绝对路径。
- 其中 `<python_cmd>` 表示当前环境可用的 Python 启动命令：Windows / PowerShell 优先 `py -3`，其次 `python`，最后 `python3`；类 Unix 环境优先 `python3`，其次 `python`。

## 何时启用

- 新功能、重构、跨模块多文件改动。
- 接口、配置、数据结构变更。
- 依赖升级。
- 性能、安全、稳定性问题。
- 需求存在关键不确定点。
- 用户明确要求“先给方案”或“遵循结构化开发工作流”。

边界清晰、低风险、可快速验证的小改动，不需要把流程写得很重，但不能跳过必要复查和验证。

## 工作流

1. 先生成变更简报。
   - 优先执行 `<python_cmd> <skill_root>/run.py change_plan --repo <repo> --paths <paths...> [flags]`
   - 用它先判断走 light 还是 full 模式，并拿到阶段、验证要求和建议串联的 skill。
2. 研究与分析
   - 检查目标、预期结果、边界范围、约束条件，并确认项目事实入口与验证路径。
3. 方案构思
   - 先给推荐方案；只有在存在明显分歧、高风险或用户明确要求时，才展开备选方案比较。
4. 代码开发
   - 在动手前明确涉及文件、核心函数或类、关键改动点；优先做最小闭环改动。
5. 复查
   - 独立检查逻辑、边界、回归、契约、异常处理、测试缺口，以及性能/安全/稳定性风险。
6. 编译与验证
   - 执行受影响范围内的最小充分验证；失败就继续修复，直到通过或确认外部阻塞。

## 过程要求

- 输出可以折叠，但步骤不能省掉关键判断。
- 只在确有增量价值时展开背景和解释。
- 不把多个不确定改动打包在一起。
- 同一问题连续多次修改仍未解决时，要回退并换路径，不连续叠加猜修。
- 在边界不清时，优先串联 `project-onboarding`；在 bugfix/失败修复任务里，优先串联 `verification-and-debug`；交付前需要独立复查时，串联 `code-review-checklist`。

## 不要这样做

- 还没弄清边界就开始大改。
- 还没方案就顺手重构无关代码。
- 还没验证就宣布完成。
- 因为赶时间而跳过复查。

## 深入参考

- 需要更具体的启用判断或输出模板时，读取 [references/workflow-decision.md](references/workflow-decision.md)。
- 需要判断什么时候串联其他 skill 时，读取 [references/skill-composition.md](references/skill-composition.md)。
