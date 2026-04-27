# macOS Build Baseline

## 适用范围

本文件说明 HarmonyOS / OpenHarmony 项目在 Mac 本机进行 hvigor 环境探测和构建验证时的环境假设与判定规则。

它只在你确实需要 Mac 本机环境结论或构建结论时适用。纯文档、注释、提示词、README 或其他明显不影响构建链路的小改动，应优先用更便宜的最小充分验证覆盖风险。

## 最终结论规则

- 只有实际运行了 `verify --task <task>` 且任务成功，才能说 Mac 本机 hvigor 验证通过。
- `detect` 默认运行 `hvigor tasks` 作为环境 preflight；它能证明环境和任务列表可用，但不能替代具体构建任务。preflight 默认超时为 120 秒，可用 `detect --timeout-seconds <seconds>` 覆盖；非 JSON 模式会在等待 hvigor 前输出 preflight 进度。
- `detect --skip-preflight` 只代表静态探测，不代表 hvigor 已验证。
- `build` 是面向 agent 的高层构建入口，会自动列出公开 tasks、选择构建任务并运行；自动列任务阶段成功时读取完整 tasks 输出用于解析公开任务，非 JSON 模式会输出阶段进度，最终输出成功/失败、阶段、任务、退出码和耗时。成功时不回传 hvigor 日志，失败时才回传错误尾部。
- `build --timeout-seconds` 是整条 build flow 的 hvigor 等待预算，默认 900 秒；自动 `hvigor tasks` 阶段默认 `--list-timeout-seconds 120`，避免任务列表阶段长时间空等。超时后进程清理会有短暂兜底等待。
- `verify --task <task>` 在没有可用缓存时不会先插入 `hvigor tasks`；它只做静态探测，然后直接运行目标任务。

## 已验证的工具链形态

- 仓库路径必须是 Mac 本机可访问路径。
- Harmony 项目标记通常包括：
  - `build-profile.json5`
  - `hvigorfile.ts`
  - `hvigorfile.js`
  - `oh-package.json5`
  - `AppScope/app.json5`
- Node 通过 `NODE_HOME`、`PATH` 或常见 Homebrew 路径解析。
- Java 优先使用显式 `JAVA_HOME`；仅当未设置 `JAVA_HOME` 且候选 Java 是 `/usr/bin/java` 启动器时，才通过 `/usr/libexec/java_home` 解析真实 JDK home，避免把 `/usr/bin/java` 反推成 `/usr`。
- Harmony SDK 通过以下候选来源解析：
  - `DEVECO_SDK_HOME`
  - `HOS_SDK_HOME`
  - `OHOS_SDK_HOME`
  - `~/Library/OpenHarmony/Sdk`
  - `~/Library/Huawei/Sdk`
  - `~/Library/Application Support/Huawei/DevEcoStudio/Sdk`
  - DevEco Studio `.app` 包内的 `Contents/sdk` / `Contents/Sdk`
- SDK 选择会参考项目 `build-profile.json5` 的 `runtimeOS`：
  - `runtimeOS: "HarmonyOS"` 时，优先选择包含 `default/hms` 与 `default/openharmony` 的 DevEco SDK 根目录，例如 `DevEco-Studio.app/Contents/sdk`。
  - OpenHarmony API 版本目录，例如 `~/Library/OpenHarmony/Sdk/<api>`，不能单独满足 HarmonyOS / HMS 构建链路。
  - `runtimeOS: "OpenHarmony"` 或未识别 `runtimeOS` 时，仍保留 OpenHarmony 版本目录作为候选。
- hvigor 优先使用项目根目录的 `hvigorw` / `hvigor`，其次使用 `PATH` 或 DevEco Studio `.app` 内的 hvigor。

## 探测策略

1. 解析本地仓库路径。
2. 识别 Harmony 项目标记。
3. 解析 Node、Java、Harmony SDK、DevEco Studio、`ohpm`、`hdc` 和 hvigor。
4. 默认以 120 秒超时运行 `hvigor tasks` 做 preflight，非 JSON 模式会先输出进度。
5. preflight 成功后保存按仓库隔离的 ready baseline。
6. 后续验证默认复用 baseline；没有 baseline 时，`verify` 直接运行目标任务，任务成功后再保存 baseline。

## 错误映射

### `harmony_project_markers_missing`

- 含义：当前目录不像 Harmony 项目根。
- 处理：确认 `--repo` 是否指向项目根，而不是上级工作区或模块外目录。

### `node_missing`

- 含义：当前进程无法解析 Node。
- 处理：确认 Node 是否已安装，并检查 `PATH` / `NODE_HOME` 是否对当前终端生效。

### `sdk_missing`

- 含义：未找到可识别的 Harmony SDK 根。
- 处理：优先确认 DevEco Studio SDK 是否已安装；HarmonyOS 项目应让 `DEVECO_SDK_HOME` 指向 DevEco 的 SDK 根目录，而不是只指向 OpenHarmony API 版本目录。

### `hvigor_missing_or_not_executable`

- 含义：未找到可执行的 `hvigorw` / `hvigor`。
- 处理：优先检查项目根是否包含 wrapper；如果 `hvigorw` 存在但不可执行，先在项目根执行 `chmod +x hvigorw` 后重试。此状态不能视为 ready，即使 PATH 上还有其他 hvigor。

### `hvigor_preflight_failed`

- 含义：静态环境要素齐全，但 `hvigor tasks` 失败。
- 处理：读取输出尾部，先修最早的环境或配置错误，不要把失败直接归因到业务代码。

## 结论输出规则

- 如果 `detect` 命中缓存且缓存来自成功 preflight，可以说当前仓库复用了已验证 ready baseline。
- 如果 `detect --skip-preflight` 成功，只能说静态依赖存在。
- 如果 `build` 成功，可以说自动选择的 Mac 本机 hvigor 构建任务通过，不需要复述 hvigor 成功日志；如果失败，报告 `BUILD FAILED` 中的阶段、任务、退出码、是否超时和输出尾部。
- 如果 `verify` 成功，可以明确说 Mac 本机对应 hvigor 任务通过。
- 如果 `verify` 失败，直接报告任务失败和输出尾部，不要替用户脑补根因。
- 不要默认运行 `assembleApp`；优先选能证明当前结论的最小公开 hvigor 任务。
