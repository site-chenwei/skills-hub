---
name: harmony-build
description: Use when a task needs HarmonyOS or OpenHarmony Windows-side hvigor build verification from either WSL or native Windows, including repo path resolution, NODE_HOME and DEVECO_SDK_HOME detection, repo-scoped ready-baseline caching, hvigor preflight checks, and troubleshooting errors such as missing NODE_HOME, invalid DEVECO_SDK_HOME, SDK component missing, or Windows build environment drift.
---

# Harmony Build

## 概述

这个 Skill 用于 HarmonyOS / OpenHarmony 项目的 Windows 侧构建验证。它会解析仓库路径、探测 `NODE_HOME` / `DEVECO_SDK_HOME` / `hvigorw.bat`、识别常见环境漂移，并在需要时通过 PowerShell 注入有效环境后执行 Windows 原生 `hvigorw.bat`。一次完整探测成功后，会按仓库缓存一个 ready baseline；后续同仓库任务默认复用它，而不是每次重新探测。

它不是“每次改完代码都要自动编译”的通用规则。只有在需要给出 Harmony Windows 侧构建结论，或改动明显影响构建/打包/签名链路时，才进入 `verify`。边界清晰的小改动应继续遵循“受影响范围内的最小充分验证”。

## 运行约定

- 先把 `<skill_root>` 设为当前已打开 `SKILL.md` 的所在目录。
- Python 入口统一通过 `<python_cmd> <skill_root>/run.py ...` 调用，不要手拼 `scripts/harmony_build.py` 的绝对路径。
- 其中 `<python_cmd>` 表示当前环境可用的 Python 启动命令：Windows / PowerShell 优先 `py -3`，其次 `python`，最后 `python3`；类 Unix 环境优先 `python3`，其次 `python`。
- 仅在明确需要 PowerShell 包装时，才直接使用 `.\scripts\harmony_build.ps1`。

## 何时使用

- 用户要求编译、打包、签名、安装或验证 HarmonyOS 项目。
- 用户要求排查 `hvigorw.bat` 在 Windows 上的失败原因。
- 用户提到 `NODE_HOME`、`DEVECO_SDK_HOME`、`SDK component missing`、`hvigor daemon` 等错误。
- 当前编辑环境在 WSL，但最终构建结论必须以 Windows 原生工具链为准。
- 仓库路径可能是 `/mnt/<drive>/...`，也可能已经是 `D:\...`。

## 何时不要默认使用

- 只是做文档、注释、提示词、README、纯文案之类不影响 Harmony 构建链路的改动。
- 改动边界很小，且已有更便宜的最小充分验证可以覆盖主要风险，例如单元测试、静态检查或脚本级回归。
- 用户没有要求构建结论，而你也不需要用 Windows 侧 `hvigorw.bat` 来证明本次改动是否成立。

## 编译验证声明

- 默认不编译。`harmony-build` 不是“只要改了 Harmony 项目代码就跑编译”的工作流。
- 只有命中以下任一条件时，才进入 Windows 侧编译验证：
  - 用户明确要求编译、打包、签名、安装，或要求确认“是否能构建通过”。
  - 你需要给出最终的 Windows 侧构建结论。
  - 改动明显影响 hvigor 构建链路，例如 `build-profile.json5`、`hvigorfile.*`、模块依赖、签名配置、打包配置、构建脚本、工具链或 SDK/Node 相关配置。
  - 更便宜的最小验证已经不足以覆盖风险，且问题大概率位于构建层。
- 命中以下情况时，不应默认进入编译验证：
  - 文档、注释、提示词、README、纯文案修改。
  - 仅改测试、脚本说明、非构建链路的辅助代码，且已有更小验证覆盖。
  - 小范围代码改动可以通过单测、静态检查、脚本级回归或手工最小路径验证充分证明。
  - 用户没有要构建结论，你也不打算输出“Windows 侧构建通过/失败”。
- 即使决定进入 `harmony-build`，也按下面的优先级选动作，而不是直接跑 `assembleApp`：
  - 只确认环境是否 ready：`detect`
  - 需要模块或特定任务结论，且你已经知道更小的有效任务名：直接运行 `verify --task <smaller-task>`
  - 需要最终构建验证时：直接运行当前最小可证明的编译任务，不要先执行 `verify --task tasks`
  - 只有明确需要 App 级产物结论时，才运行 `verify --task assembleApp`

## 工作流

1. 解析仓库路径。
   - WSL 调用支持 `<repo-wsl-path>` 和 `<repo-windows-path>`。
   - Windows 原生调用支持 `<repo-windows-path>`，也支持在仓库目录内直接省略 `--repo`。
   - 如果仓库无法解析到 Windows 驱动器路径，不要给出最终 Windows 构建结论。
2. 首次建立或显式刷新环境基线。
   - 示例：
     - `<python_cmd> <skill_root>/run.py detect --repo <repo-path>`
     - `.\scripts\harmony_build.ps1 detect --repo <repo-windows-path>`
   - 默认情况下，`detect` 会探测 SDK 候选根，并用 `hvigorw.bat tasks` 做一次 preflight；ready 时会把结果保存成该仓库的缓存基线。
   - 后续再次执行 `detect` 时，若该仓库已有可用 ready baseline，会直接复用缓存并快速返回。
   - 只有在你明确传了 `--refresh` 时，`detect` 才会忽略缓存、重跑完整探测。
   - 只有在你明确传了 `--skip-sdk-probe` 时，`detect` 才不会执行 preflight；这种静态探测不会刷新缓存基线。
   - 缓存目录统一遵循 `skills-hub/<skill-name>` 约定；可用 `SKILLS_HUB_RUNTIME_DIR` 覆盖共享根目录。
3. 如果第 2 步已经得到 ready baseline，后续同仓库工作流默认直接认定环境 OK。
   - `verify` 和 `print-env` 默认先复用该基线，不必手动再跑一次 `detect`。
   - 仅在以下场景加 `--refresh`：
     - 刚修改过 `NODE_HOME`、`DEVECO_SDK_HOME`、DevEco Studio、Node 或 SDK 安装
     - 切换了目标仓库
     - 缓存命中的 `verify` 报出环境类错误
4. 如果基线不完整、存在歧义，或需要解释错误来源，读取 `references/windows-build-baseline.md`。
5. 不把 `verify --task tasks` 放进默认构建路径。
   - 它不是构建验证前置步骤，也不用来“先找更小任务”。
   - 只有在用户明确要求查看任务列表，或你正在排查 hvigor / 环境问题时，才单独运行它。
6. 仅在需要最终构建结论时运行实际构建验证。
   - 典型触发场景：
     - 用户明确要求编译、打包、签名、安装或“确认构建是否通过”
     - 改动涉及构建脚本、依赖、配置、模块接线、产物打包或其他明显影响 hvigor 结果的内容
     - 你准备给出“Windows 侧构建通过/失败”的最终结论
   - 不要把 `assembleApp` 当成默认任务；优先选择能支撑当前结论的最小 hvigor 任务。
   - 需要构建验证时，直接发起所选编译任务；不要在前面再插入一轮 `verify --task tasks`。
   - 如果你已知更小任务名，就直接跑它；如果没有，就直接跑当前最小可证明任务，而不是先做 task 探测。
   - 只有在用户明确需要 App 级产物、安装包，或改动明显影响 App 聚合打包链路时，才使用 `assembleApp`。
   - 示例：
     - `<python_cmd> <skill_root>/run.py verify --repo <repo-path> --task <task>`
     - `.\scripts\harmony_build.ps1 verify --repo <repo-windows-path> --task <task>`
7. 明确说明结论来源：
   - 是来自 Windows 侧 `hvigorw.bat` 实际验证
   - 还是仅来自静态检查 / 环境探测 / 已缓存的 ready baseline

占位符说明：

- `<repo-wsl-path>`：例如 `/mnt/d/WorkSpace/DNSHelper`
- `<repo-windows-path>`：例如 `D:\WorkSpace\DNSHelper`

## 入口脚本

- `<skill_root>/run.py detect`
  - 探测运行宿主、仓库本地路径、仓库 Windows 路径、`NODE_HOME`、`node.exe`、`DEVECO_SDK_HOME`、`hvigorw.bat` 和 NVM 残留。
  - 默认会 probe SDK 候选根，并通过 `hvigorw.bat tasks` 选出第一个可工作的 SDK 根。
  - ready 时会把结果保存成按仓库隔离的缓存基线；后续默认优先复用该基线。
  - `--refresh` 用于忽略缓存并重跑完整探测。
  - `--skip-sdk-probe` 用于跳过 preflight，只做静态环境探测；它不会刷新缓存基线。

- `<skill_root>/run.py verify`
  - 默认优先复用缓存基线；缺失、失效或显式 `--refresh` 时，才重新探测并刷新基线。
  - 重新构建 Windows `Path`，并把已解析出的 `NODE_HOME` 与 `DEVECO_SDK_HOME` 注入到 PowerShell 会话。
  - 在仓库对应的 Windows 路径下执行 `hvigorw.bat <task>`。
  - hvigor 输出会重定向到临时文件，进程退出后只读取尾部摘要，避免 daemon / worker 继承 stdout/stderr pipe 后拖住 Python 包装层。
  - 默认硬超时为 900 秒，可用 `--timeout-seconds <seconds>` 覆盖。
  - `--task` 必须是公开 hvigor task 名；不要传 `.hvigor` 内部 key，例如 `:entry:default@CompileArkTS`。
  - 如果环境未 ready，会直接返回 `exit_code = 1`，不会启动 `hvigorw.bat`。
  - 如果缓存命中的验证报出典型环境错误，会自动刷新一次基线后重试。

- `<skill_root>/run.py print-env`
  - 默认优先复用缓存基线；显式 `--refresh` 时重新探测。
  - 输出一个 PowerShell 片段，便于在旧终端中手动注入环境后重试。
  - 它依赖仓库 Windows 路径、`NODE_HOME` 和 `DEVECO_SDK_HOME` 都已成功解析；缺任一项都会失败。

- `scripts/harmony_build.ps1`
  - Windows PowerShell 包装入口，内部转调 `harmony_build.py`。
  - Python 查找顺序是 `py -3` → `python` → `python3`。

## 输出规则

- 只有在需要给出最终构建结论时，才要求使用 Windows 侧 `verify`。
- 同仓库已有 ready baseline 时，可以把环境判定直接建立在该基线之上；不要机械地重复跑 `detect`。
- 需要构建验证时，直接运行目标编译任务；不要把 `verify --task tasks` 作为默认前置步骤。
- 不要把“小改动也默认重跑编译”当成工作流常态；优先选择受影响范围内的最小充分验证。
- 不要把 `assembleApp` 当成默认验证命令；除非本次任务确实需要 App 级产物结论。
- `hvigor daemon failed to listen on the port` 在后续退回 `no-daemon mode` 且命令成功时，不视为阻塞。
- 如果没有找到可工作的 SDK 根，报告环境阻塞，不要猜测代码问题。
- 不要默认把 `...\\sdk\\default` 或 `...\\OpenHarmony\\Sdk` 当成最终 `DEVECO_SDK_HOME`，除非 probe 已证明该值可工作。
- 如果仓库本身不在 Windows 驱动器映射上，必须明确说明“无法形成最终 Windows 构建结论”。

## 参考资料

- 当需要已验证的基线路径、错误映射、或双环境判定规则时，读取 `references/windows-build-baseline.md`。
