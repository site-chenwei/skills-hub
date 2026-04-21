---
name: project-onboarding
description: Use this skill when entering an unfamiliar repository, before cross-module work, or when the user asks to first understand the project, architecture, constraints, README/PROJECT.md context, validation paths, or stack signals. Triggers include PROJECT.md, README, architecture review, codebase tour, boundary analysis, stack discovery, and repo fact extraction.
---

# 项目入口对齐

在真正修改代码前，先抽出项目事实、任务边界、约束条件和验证路径，避免在陌生仓库里靠猜推进。

## 运行约定

- 先把 `<skill_root>` 设为当前已打开 `SKILL.md` 的所在目录。
- 所有辅助脚本统一通过 `python3 <skill_root>/run.py ...` 调用，不要手拼 `scripts/*.py` 的绝对路径，也不要假设 Skill 一定位于 `~/.codex/skills/.system/` 下。

## 何时使用

- 初次进入陌生仓库，或当前上下文不足以安全动手。
- 开始跨模块、多文件、高风险改动前。
- 用户要求“先理解项目”“先看 `PROJECT.md` / `README`”“先梳理架构、边界、约束”。
- 需要快速判断本次任务会影响哪些模块、配置、数据流或验证入口。

低风险且位置明确的单文件问题，不需要把整套流程全部展开，但仍应先核实关键事实。

## 工作流

1. 先跑事实扫描。
   - 优先执行 `python3 <skill_root>/run.py project_facts --repo <repo> --format markdown`
   - 用它先拿到文档入口、技术栈信号、顶层目录、验证命令候选和待确认项。
2. 再读关键入口。
   - 默认顺序是 `PROJECT.md` -> `README*` -> 顶层配置文件 -> `docs/` -> 关键入口源码与测试。
   - 只补读和当前任务直接相关的文件，不做无边界漫游。
3. 提取五类事实。
   - 目标、预期结果、边界范围、约束条件、验证路径。
4. 落到本次任务。
   - 明确涉及文件、核心模块、调用链、数据结构、配置项和潜在回归面。
5. 区分事实层级。
   - 已确认事实、基于证据的推断、仍待确认的问题必须分开写。

## 输出要求

- 先给结论，不复述用户请求。
- 默认使用简短清单：
  目标、边界、约束、关键入口、影响面、验证方式、风险与待确认。
- 只有当缺失信息会改变执行路径时才追问。
- 不把 README 的宣传描述直接当作真实实现。
- 如果用了 `project_facts.py`，优先复用其中“已确认 / 推断 / 待确认”的结构，而不是重新组织成松散描述。

## 不要这样做

- 未读入口文档就预设架构。
- 只看单个目录就下全局结论。
- 把推测写成事实。
- 在没有验证入口的情况下声称“已经理解清楚”。

## 深入检查时

- 需要更细的入项清单时，读取 [references/intake-checklist.md](references/intake-checklist.md)。
- 需要按技术栈判断该读哪些配置、测试和入口文件时，读取 [references/stack-signals.md](references/stack-signals.md)。
