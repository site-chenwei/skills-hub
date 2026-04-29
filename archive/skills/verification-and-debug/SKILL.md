---
name: verification-and-debug
description: Use this skill for build failures, failing tests, runtime bugs, regressions, flaky behavior, and performance or stability issues. It enforces reproduce-first debugging, structured failure capture, layered fault isolation, minimal fixes, and explicit verification after each change.
---

# 验证与排障

先稳定复现，再定位故障层，再做最小修复并重新验证；不靠连续猜修换取表面“可运行”。

## 运行约定

- 先把 `<skill_root>` 设为当前已打开 `SKILL.md` 的所在目录。
- 所有辅助脚本统一通过 `<python_cmd> <skill_root>/run.py ...` 调用，不要手拼 `scripts/*.py` 的绝对路径。
- 其中 `<python_cmd>` 表示当前环境可用的 Python 启动命令：Windows / PowerShell 优先 `py -3`，其次 `python`，最后 `python3`；类 Unix 环境优先 `python3`，其次 `python`。
- `<skill_root>` 只能由本次实际打开的 `SKILL.md` 路径推导；不要根据 Skill 名称、同名目录、`.system`、`builtin`、`installed` 等目录习惯切换到其他路径。
- 调用 `run.py`、`scripts/`、`references/`、模板或其他附件前，先在 `<skill_root>` 下显式确认目标存在；不存在时报告附件缺失并回退手工流程。
- 对用户说明使用本 Skill 时，区分已确认入口文件、推导出的根目录和已检查存在的附件。

## 何时使用

- 编译失败、测试失败、运行时报错、回归、卡死、异常输出。
- 用户说“为什么不工作了”“帮我排障”“先定位根因”。
- 性能、稳定性或多组件链路问题。

## 核心规则

- 不引入新的静默降级、伪成功、吞错、假数据或假执行路径。
- 不在没有重新执行验证命令前声称“已修复”“已完成”“测试通过”。
- 捕获日志、命令输出或失败上下文时，避免泄露密码、API Key、令牌、`.env` 和测试凭据；需要展示时只保留定位根因所需的最小摘录。
- 对外部输入、环境变量、命令参数和文件路径做边界判断；失败要显式暴露，不用默认值或假数据伪造成功。
- 优先修根因，不修表象。
- 能稳定复现时，先记录失败命令和环境，再决定加哪些观察点。

## 工作流

1. 先捕获失败上下文。
   - 可复现时优先执行 `<python_cmd> <skill_root>/run.py capture_failure --cwd <repo> -- <cmd>`
   - 也可使用高层别名 `<python_cmd> <skill_root>/run.py check ...` 或 `triage ...`，二者等价于 `capture_failure`。
   - 先拿到退出码、stdout/stderr 尾部、初步分类和下一步建议。
2. 稳定复现并判断故障层级。
   - 先判断问题位于构建、测试、运行时、配置、依赖、网络、权限还是外部系统。
3. 补观察点。
   - 只增加必要日志、断点、断言或临时检查，不做大面积噪声打印。
4. 基于证据提出根因假设。
   - 假设必须能解释现象；解释不了的线索不能强行忽略。
5. 做最小修复。
   - 避免把多个不确定修改绑在一起。
6. 重新验证。
   - 先跑最小充分验证；高风险问题再扩大验证范围。

## 卡住时

- 同一问题连续多次修改仍未解决时，要回退并换路径。
- 如果是外部阻塞，要明确写出阻塞点、失败命令、缺失前提和剩余不确定性。

## 深入参考

- 需要更细的排障清单时，读取 [references/debug-checklist.md](references/debug-checklist.md)。
- 需要把常见错误模式映射到故障层级和下一步动作时，读取 [references/failure-patterns.md](references/failure-patterns.md)。
