# macOS Build Baseline

## 适用范围

本文件说明 HarmonyOS / OpenHarmony 项目在 Mac 本机进行 hvigor 环境探测和构建验证时的环境假设与判定规则。

它只在你确实需要 Mac 本机环境结论或构建结论时适用。纯文档、注释、提示词、README 或其他明显不影响构建链路的小改动，应优先用更便宜的最小充分验证覆盖风险。

## 最终结论规则

- 只有实际运行了 `verify --task <task>` 且任务成功，才能说 Mac 本机 hvigor 验证通过。
- `detect` 默认运行 `hvigor tasks` 作为环境 preflight；它能证明环境和任务列表可用，但不能替代具体构建任务。
- `detect --skip-preflight` 只代表静态探测，不代表 hvigor 已验证。
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
- Java 通过 `JAVA_HOME`、`PATH` 或 `/usr/bin/java` 解析。
- Harmony SDK 通过以下候选来源解析：
  - `DEVECO_SDK_HOME`
  - `HOS_SDK_HOME`
  - `OHOS_SDK_HOME`
  - `~/Library/OpenHarmony/Sdk`
  - `~/Library/Huawei/Sdk`
  - `~/Library/Application Support/Huawei/DevEcoStudio/Sdk`
  - DevEco Studio `.app` 包内的 `Contents/sdk` / `Contents/Sdk`
- hvigor 优先使用项目根目录的 `hvigorw` / `hvigor`，其次使用 `PATH` 或 DevEco Studio `.app` 内的 hvigor。

## 探测策略

1. 解析本地仓库路径。
2. 识别 Harmony 项目标记。
3. 解析 Node、Java、Harmony SDK、DevEco Studio、`ohpm`、`hdc` 和 hvigor。
4. 默认运行 `hvigor tasks` 做 preflight。
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
- 处理：优先确认 DevEco Studio SDK 是否已安装；必要时设置 `DEVECO_SDK_HOME` 指向实际 SDK 版本目录。

### `hvigor_missing_or_not_executable`

- 含义：未找到可执行的 `hvigorw` / `hvigor`。
- 处理：优先检查项目根是否包含 wrapper；如果存在但不可执行，修正文件权限后重试。

### `hvigor_preflight_failed`

- 含义：静态环境要素齐全，但 `hvigor tasks` 失败。
- 处理：读取输出尾部，先修最早的环境或配置错误，不要把失败直接归因到业务代码。

## 结论输出规则

- 如果 `detect` 命中缓存且缓存来自成功 preflight，可以说当前仓库复用了已验证 ready baseline。
- 如果 `detect --skip-preflight` 成功，只能说静态依赖存在。
- 如果 `verify` 成功，可以明确说 Mac 本机对应 hvigor 任务通过。
- 如果 `verify` 失败，直接报告任务失败和输出尾部，不要替用户脑补根因。
- 不要默认运行 `assembleApp`；优先选能证明当前结论的最小公开 hvigor 任务。
