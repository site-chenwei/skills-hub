---
name: harmony-build
description: Use when a task needs HarmonyOS or OpenHarmony Windows-side hvigor build verification from either WSL or native Windows, including repo path resolution, NODE_HOME and DEVECO_SDK_HOME detection, repo-scoped ready-baseline caching, hvigor preflight checks, and troubleshooting errors such as missing NODE_HOME, invalid DEVECO_SDK_HOME, SDK component missing, or Windows build environment drift.
---

# Harmony Build

## 概述

这个 Skill 用于 HarmonyOS / OpenHarmony 项目的 Windows 侧构建验证。它会解析仓库路径、探测 `NODE_HOME` / `DEVECO_SDK_HOME` / `hvigorw.bat`、识别常见环境漂移，并在需要时通过 PowerShell 注入有效环境后执行 Windows 原生 `hvigorw.bat`。一次完整探测成功后，会按仓库缓存一个 ready baseline；后续同仓库任务默认复用它，而不是每次重新探测。

## 何时使用

- 用户要求编译、打包、签名、安装或验证 HarmonyOS 项目。
- 用户要求排查 `hvigorw.bat` 在 Windows 上的失败原因。
- 用户提到 `NODE_HOME`、`DEVECO_SDK_HOME`、`SDK component missing`、`hvigor daemon` 等错误。
- 当前编辑环境在 WSL，但最终构建结论必须以 Windows 原生工具链为准。
- 仓库路径可能是 `/mnt/<drive>/...`，也可能已经是 `D:\...`。

## 工作流

1. 解析仓库路径。
   - WSL 调用支持 `<repo-wsl-path>` 和 `<repo-windows-path>`。
   - Windows 原生调用支持 `<repo-windows-path>`，也支持在仓库目录内直接省略 `--repo`。
   - 如果仓库无法解析到 Windows 驱动器路径，不要给出最终 Windows 构建结论。
2. 首次建立或显式刷新环境基线。
   - 示例：
     - `python3 scripts/harmony_build.py detect --repo <repo-wsl-path>`
     - `python scripts/harmony_build.py detect --repo <repo-windows-path>`
     - `.\scripts\harmony_build.ps1 detect --repo <repo-windows-path>`
   - 默认情况下，`detect` 会探测 SDK 候选根，并用 `hvigorw.bat tasks` 做一次 preflight；ready 时会把结果保存成该仓库的缓存基线。
   - 后续再次执行 `detect` 时，若该仓库已有可用 ready baseline，会直接复用缓存并快速返回。
   - 只有在你明确传了 `--refresh` 时，`detect` 才会忽略缓存、重跑完整探测。
   - 只有在你明确传了 `--skip-sdk-probe` 时，`detect` 才不会执行 preflight；这种静态探测不会刷新缓存基线。
3. 如果第 2 步已经得到 ready baseline，后续同仓库工作流默认直接认定环境 OK。
   - `verify` 和 `print-env` 默认先复用该基线，不必手动再跑一次 `detect`。
   - 仅在以下场景加 `--refresh`：
     - 刚修改过 `NODE_HOME`、`DEVECO_SDK_HOME`、DevEco Studio、Node 或 SDK 安装
     - 切换了目标仓库
     - 缓存命中的 `verify` 报出环境类错误
4. 如果基线不完整、存在歧义，或需要解释错误来源，读取 `references/windows-build-baseline.md`。
5. 仅在以下场景补跑显式 preflight：
   - 第 2 步使用了 `--skip-sdk-probe`
   - 你需要一个单独、可复述的 `tasks` 验证结果
   - 示例：
     - `python3 scripts/harmony_build.py verify --repo <repo-wsl-path> --task tasks`
     - `python scripts/harmony_build.py verify --repo <repo-windows-path> --task tasks`
     - `.\scripts\harmony_build.ps1 verify --repo <repo-windows-path> --task tasks`
6. 运行实际构建验证。
   - 示例：
     - `python3 scripts/harmony_build.py verify --repo <repo-wsl-path> --task assembleApp`
     - `python scripts/harmony_build.py verify --repo <repo-windows-path> --task assembleApp`
     - `.\scripts\harmony_build.ps1 verify --repo <repo-windows-path> --task assembleApp`
7. 明确说明结论来源：
   - 是来自 Windows 侧 `hvigorw.bat` 实际验证
   - 还是仅来自静态检查 / 环境探测 / 已缓存的 ready baseline

占位符说明：

- `<repo-wsl-path>`：例如 `/mnt/d/WorkSpace/DNSHelper`
- `<repo-windows-path>`：例如 `D:\WorkSpace\DNSHelper`

## 入口脚本

- `scripts/harmony_build.py detect`
  - 探测运行宿主、仓库本地路径、仓库 Windows 路径、`NODE_HOME`、`node.exe`、`DEVECO_SDK_HOME`、`hvigorw.bat` 和 NVM 残留。
  - 默认会 probe SDK 候选根，并通过 `hvigorw.bat tasks` 选出第一个可工作的 SDK 根。
  - ready 时会把结果保存成按仓库隔离的缓存基线；后续默认优先复用该基线。
  - `--refresh` 用于忽略缓存并重跑完整探测。
  - `--skip-sdk-probe` 用于跳过 preflight，只做静态环境探测；它不会刷新缓存基线。

- `scripts/harmony_build.py verify`
  - 默认优先复用缓存基线；缺失、失效或显式 `--refresh` 时，才重新探测并刷新基线。
  - 重新构建 Windows `Path`，并把已解析出的 `NODE_HOME` 与 `DEVECO_SDK_HOME` 注入到 PowerShell 会话。
  - 在仓库对应的 Windows 路径下执行 `hvigorw.bat <task>`。
  - 如果环境未 ready，会直接返回 `exit_code = 1`，不会启动 `hvigorw.bat`。
  - 如果缓存命中的验证报出典型环境错误，会自动刷新一次基线后重试。

- `scripts/harmony_build.py print-env`
  - 默认优先复用缓存基线；显式 `--refresh` 时重新探测。
  - 输出一个 PowerShell 片段，便于在旧终端中手动注入环境后重试。
  - 它依赖仓库 Windows 路径、`NODE_HOME` 和 `DEVECO_SDK_HOME` 都已成功解析；缺任一项都会失败。

- `scripts/harmony_build.ps1`
  - Windows PowerShell 包装入口，内部转调 `harmony_build.py`。
  - Python 查找顺序是 `py -3` → `python` → `python3`。

## 输出规则

- 最终构建结论必须来自 Windows 侧 `verify`。
- 同仓库已有 ready baseline 时，可以把环境判定直接建立在该基线之上；不要机械地重复跑 `detect`。
- `hvigor daemon failed to listen on the port` 在后续退回 `no-daemon mode` 且命令成功时，不视为阻塞。
- 如果没有找到可工作的 SDK 根，报告环境阻塞，不要猜测代码问题。
- 不要默认把 `...\\sdk\\default` 或 `...\\OpenHarmony\\Sdk` 当成最终 `DEVECO_SDK_HOME`，除非 probe 已证明该值可工作。
- 如果仓库本身不在 Windows 驱动器映射上，必须明确说明“无法形成最终 Windows 构建结论”。

## 参考资料

- 当需要已验证的基线路径、错误映射、或双环境判定规则时，读取 `references/windows-build-baseline.md`。
