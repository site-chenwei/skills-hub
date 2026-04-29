# Skill 串联规则

## 先串联 `project-onboarding`

- 仓库陌生、影响面不清、涉及多个模块或多个技术栈
- 需要先确认最小验证命令、关键入口、约束和边界
- 需要判断 Harmony、Java、React Web 的入口、风险信号和验证候选

## 先串联 `verification-and-debug`

- 任务起点是失败命令、报错、测试回归、构建失败或线上故障
- 需要先稳定复现并锁定故障层，再进入方案与实现

## 收尾串联 `code-review-checklist`

- 改动跨文件、涉及契约、依赖、schema、配置或高风险逻辑
- 需要独立视角复查回归、测试缺口和交付风险
- Harmony 页面结构 / 资源 / 构建配置、Java API / DTO / migration / config、React routing / SSR / auth / schema / design-system 等高风险路径

## 交付阶段串联 `git-delivery`

- 用户要求 stage、commit、push、publish、close out 或交付当前仓库改动
- 上一轮 Git 操作中断、超时或状态不明确，需要重新确认工作区和 upstream
- 需要区分源码改动、系统文件、诊断日志、凭据风险、生成副作用和 staged diff hygiene

## 维护 Skill 仓库时串联 `skill-repo-lifecycle`

- 新增或修改 repo-owned Skill 的 `SKILL.md`、`agents/openai.yaml`、`run.py`、`scripts/`、`references/` 或测试
- 需要确认 `skills.test_all_skills`、共享测试、安装副本 parity 或 `/Users/bill/.cc-switch/skills` 运行态
- 需要判断用户级 AGENTS 规则是否已下沉到对应 Skill，或避免把仓库状态干净误判成仓库外文件未改

## 不必强行串联

- 单文件、小修复、边界明确且验证简单
- 额外串联不会新增判断价值，只会重复已有事实
- Harmony 小范围文案、样式或局部业务逻辑改动如果已有更小验证覆盖，不因项目类型强制串联 `harmony-build`
