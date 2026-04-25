---
name: harmony-build
description: Use when a task needs macOS HarmonyOS/OpenHarmony hvigor environment detection, local build/package/install verification, or troubleshooting around Node, Java, Harmony SDK, DevEco Studio, ohpm, hdc, and project hvigor wrappers.
---

# Harmony Build

## 概述

这个 Skill 用于 Mac 本机 HarmonyOS / OpenHarmony 开发验证。它会识别当前仓库是否像 Harmony 项目，探测 Node、Java、Harmony SDK、DevEco Studio、`ohpm`、`hdc` 和 `hvigorw` / `hvigor`，并在需要时运行公开 hvigor 任务。一次 `detect` preflight 成功后，会按仓库缓存 ready baseline；后续同仓库任务默认复用它，而不是机械重跑探测。

它不是“每次改完代码都要自动编译”的规则。只有在用户要求构建结论、改动影响 hvigor 构建链路，或更便宜的最小验证不足以覆盖风险时，才进入 `verify`。

## 运行约定

- 先把 `<skill_root>` 设为当前已打开 `SKILL.md` 的所在目录。
- Python 入口统一通过 `<python_cmd> <skill_root>/run.py ...` 调用，不要手拼 `scripts/harmony_build.py` 的绝对路径。
- 其中 `<python_cmd>` 表示当前环境可用的 Python 启动命令：Windows / PowerShell 优先 `py -3`，其次 `python`，最后 `python3`；类 Unix 环境优先 `python3`，其次 `python`。
- `<skill_root>` 只能由本次实际打开的 `SKILL.md` 路径推导；不要根据 Skill 名称、同名目录、`.system`、`builtin`、`installed` 等目录习惯切换到其他路径。
- 调用 `run.py`、`scripts/`、`references/`、模板或其他附件前，先在 `<skill_root>` 下显式确认目标存在；不存在时报告附件缺失并回退手工流程。
- 对用户说明使用本 Skill 时，区分已确认入口文件、推导出的根目录和已检查存在的附件。
- Mac 开发环境优先使用 zsh/bash 片段；`scripts/harmony_build.ps1` 仅是遗留 Windows 包装入口，不作为 Mac 工作流入口。

## 何时使用

- 用户要求在 Mac 上验证 HarmonyOS / OpenHarmony 项目能否构建、打包、签名或安装。
- 用户要求排查 `hvigorw`、`hvigor`、Node、Java、Harmony SDK、DevEco Studio、`ohpm` 或 `hdc` 环境问题。
- 改动明显影响 `build-profile.json5`、`hvigorfile.*`、模块依赖、签名配置、打包配置、构建脚本、工具链或 SDK/Node/Java 相关配置。
- 你需要给出“Mac 本机 hvigor 验证通过/失败”的结论。

## 何时不要默认使用

- 只是做文档、注释、提示词、README、纯文案之类不影响 Harmony 构建链路的改动。
- 改动边界很小，且已有更便宜的最小充分验证可以覆盖主要风险，例如单元测试、静态检查、脚本级回归或手工最小路径验证。
- 用户没有要求构建结论，你也不需要用 Mac 本机 hvigor 任务来证明本次改动是否成立。

## 验证声明

- 默认不升级到编译验证。`harmony-build` 不是“只要改了 Harmony 项目代码就跑编译”的工作流。
- 只有命中以下任一条件时，才进入 `verify`：
  - 用户明确要求编译、打包、签名、安装，或要求确认“是否能构建通过”。
  - 你需要给出最终 Mac 本机构建结论。
  - 改动明显进入 hvigor 构建链路。
  - 改动命中 HarmonyOS / OpenHarmony 高风险 UI 或 ArkTS 结构：页面结构、导航层级、`@Entry`、`HdsNavigation` / `HdsNavDestination` / `HdsTabs`、`NavigationBuilderRegister`、`build()` 根节点、`@Builder` / `@BuilderParam`、公共页面脚手架或资源引用接线，且源码级检查不足以覆盖风险。
  - 更便宜的最小验证不足以覆盖风险，且问题大概率位于构建层。
- 即使决定进入 `verify`，也优先选择能支撑当前结论的最小公开 hvigor 任务，不要默认使用 `assembleApp`。
- `verify --task tasks` 只用于用户要求查看任务列表，或你正在排查 hvigor / 环境漂移；它不是构建验证的默认前置步骤。

## 工作流

1. 解析仓库路径。
   - Mac 本机路径直接使用当前目录或 `--repo <repo-path>`。
   - 通过 `build-profile.json5`、`hvigorfile.*`、`oh-package.json5`、`AppScope/app.json5` 等标记判断是否像 Harmony 项目。
2. 建立或刷新环境基线。
   - 示例：`<python_cmd> <skill_root>/run.py detect --repo <repo-path>`
   - 默认情况下，`detect` 会做静态探测，并运行一次 `hvigor tasks` 作为轻量 preflight。
   - preflight 成功后保存该仓库 ready baseline；后续 `detect` / `verify` / `print-env` 默认复用缓存。
   - 只有在明确传 `--refresh` 时，才忽略缓存并重跑探测。
   - 只有在明确传 `--skip-preflight` 时，才跳过 `hvigor tasks`，只做静态探测；这种结果不会保存 ready baseline。
3. 复用或刷新基线。
   - 刚修改过 Node、Java、SDK、DevEco Studio、`ohpm`、`hdc`、项目 wrapper 或仓库路径时，加 `--refresh`。
   - 缓存命中的 `verify` 报出环境类错误时，脚本会自动刷新一次基线后重试。
4. 需要解释环境阻塞、缓存策略或失败映射时，读取 `references/macos-build-baseline.md`。
5. 需要最终构建结论时，直接运行当前最小可证明任务：
   - `<python_cmd> <skill_root>/run.py verify --repo <repo-path> --task <task>`
   - `--task` 必须是公开 hvigor task 名，不要传 `.hvigor` 内部 key，例如 `:entry:default@CompileArkTS`。
6. 明确说明结论来源：
   - 是来自 Mac 本机 `hvigor` / `hvigorw` 实际验证
   - 还是仅来自静态检查 / 环境探测 / 已缓存 ready baseline

## 入口脚本

- `<skill_root>/run.py detect`
  - 探测运行宿主、仓库路径、Harmony 项目标记、Node、Java、Harmony SDK、DevEco Studio、`hvigor`、`ohpm` 和 `hdc`。
  - 默认运行 `hvigor tasks` 做 preflight；ready 时保存按仓库隔离的缓存基线。
  - `--refresh` 用于忽略缓存并重跑完整探测。
  - `--skip-preflight` 用于跳过 preflight，只做静态探测。

- `<skill_root>/run.py verify`
  - 默认优先复用缓存基线；缺失、失效或显式 `--refresh` 时，只做静态探测，然后直接运行目标任务。
  - 目标任务成功后会把该仓库写入 ready baseline，后续命令可复用。
  - 注入 `DEVECO_SDK_HOME`，并在缺省时同步 `HOS_SDK_HOME` / `OHOS_SDK_HOME`。
  - 如已解析出 `NODE_HOME` / `JAVA_HOME`，会注入到 hvigor 子进程。
  - hvigor 输出会重定向到临时文件，进程退出后只读取尾部摘要，避免长日志拖慢包装层。
  - 默认硬超时为 900 秒，可用 `--timeout-seconds <seconds>` 覆盖。

- `<skill_root>/run.py print-env`
  - 默认优先复用缓存基线；显式 `--refresh` 时重新探测。
  - 输出 zsh/bash 可用的环境片段，便于在当前终端复现脚本注入的关键变量。

## 输出规则

- 只有在需要给出最终构建结论时，才要求使用 `verify`。
- 同仓库已有 ready baseline 时，可以把环境判定建立在该基线之上；不要机械地重复跑 `detect`。
- 需要构建验证时，直接运行目标编译任务；不要把 `verify --task tasks` 作为默认前置步骤。
- 不要把 `assembleApp` 当成默认验证命令；除非本次任务确实需要 App 级产物结论。
- 如果没有找到可工作的 SDK、Node 或 hvigor wrapper，报告环境阻塞，不要猜测代码问题。
- 如果只做了 `--skip-preflight` 静态探测，不要把结果说成“已通过 hvigor 验证”。

## 参考资料

- Mac 本机环境基线、候选路径和错误映射：`references/macos-build-baseline.md`。
- 旧 Windows 侧验证说明已保留在 `references/windows-build-baseline.md`，仅用于历史迁移参考。
