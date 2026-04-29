---
name: code-review-checklist
description: Use this skill when the user asks for a review, patch review, PR review, change audit, or regression check. Focus on scoping the diff first, then finding logic bugs, contract drift, missing tests, and performance, security, or stability risks with evidence.
---

# 代码审查清单

以代码评审视角审查变更，优先找出会影响行为、稳定性和可维护性的真实问题，而不是先做风格点评。

## 运行约定

- 先把 `<skill_root>` 设为当前已打开 `SKILL.md` 的所在目录。
- 所有辅助脚本统一通过 `<python_cmd> <skill_root>/run.py ...` 调用，不要手拼 `scripts/*.py` 的绝对路径。
- 其中 `<python_cmd>` 表示当前环境可用的 Python 启动命令：Windows / PowerShell 优先 `py -3`，其次 `python`，最后 `python3`；类 Unix 环境优先 `python3`，其次 `python`。
- `<skill_root>` 只能由本次实际打开的 `SKILL.md` 路径推导；不要根据 Skill 名称、同名目录、`.system`、`builtin`、`installed` 等目录习惯切换到其他路径。
- 调用 `run.py`、`scripts/`、`references/`、模板或其他附件前，先在 `<skill_root>` 下显式确认目标存在；不存在时报告附件缺失并回退手工流程。
- 对用户说明使用本 Skill 时，区分已确认入口文件、推导出的根目录和已检查存在的附件。

## 何时使用

- 用户明确说“review”“审查”“看下这次改动有没有问题”“查回归风险”。
- 需要对 diff、提交、补丁或多文件改动做静态审查。
- 需要给出 findings、风险分级、测试缺口和剩余风险。

## 审查流程

1. 先收敛范围。
   - 优先执行 `<python_cmd> <skill_root>/run.py review_scope --repo <repo> --format markdown`
   - 需要先给审查上下文包时，执行 `<python_cmd> <skill_root>/run.py review-context --repo <repo> --format markdown`；该入口基于 `review_scope` 输出范围、风险、测试缺口和下一步，不生成或伪造 findings。
   - 在有明确 base/head 时传入 `--base <rev> [--head <rev>]`
   - 先看文件分类、风险标签、测试缺口和高改动文件，再决定补读哪些上下文。
2. 再看真实风险。
   - 逻辑错误、行为回归、边界条件、接口契约不一致、异常处理缺失、测试遗漏。
3. 按需补看非功能风险。
   - 性能、安全、稳定性、并发、资源释放、迁移兼容、发布链路。
   - 凭据泄露、外部输入未校验、静默降级、伪成功、假数据、破坏性 Git 或文件操作。
4. 判断验证是否充分。
   - 检查现有测试、手工验证、构建命令是否真正覆盖受影响范围。
5. 写 finding 时保留证据。
   - 明确触发条件、影响、文件位置、为什么当前实现会出问题。

## 输出格式

- Findings 放在最前面，按严重级别排序。
- 每条 finding 要写清：
  风险点、触发条件、影响、对应文件和行号。
- 没有足够证据时，不要把怀疑写成 finding；可以放到“待确认问题”。
- 之后再写：
  待确认问题、假设、简短总结、剩余风险或测试缺口。
- 如果没有发现阻塞性问题，要明确写“未发现新的阻塞性 findings”，并补充残余风险。

## 不要这样做

- 先写长篇总结，再把 findings 埋在后面。
- 用风格偏好淹没真正的行为风险。
- 在没有运行验证命令的前提下写“测试通过”。
- 因为实现看起来整洁就忽略契约和回归风险。
- 因为 diff 小就忽略凭据、输入边界、吞错、假成功或破坏性操作。

## 深入参考

- 需要更细的审查维度时，读取 [references/review-dimensions.md](references/review-dimensions.md)。
- 需要统一 finding 严重级别和证据要求时，读取 [references/finding-severity.md](references/finding-severity.md)。
