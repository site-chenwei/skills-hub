# Windows Build Baseline

## 适用范围

本文件说明 HarmonyOS / OpenHarmony 项目在 WSL 或 Windows 原生环境下进行 Windows 侧构建验证时的环境假设与判定规则。

## 最终结论规则

- 最终构建结论必须来自 Windows 原生 `hvigorw.bat`。
- WSL 侧可以做编辑、搜索、静态分析和非最终性检查，但不能代替最终 Windows 构建结论。

## 已验证的工具链形态

- 仓库路径最终必须能解析成 Windows 驱动器路径，例如 `D:\path\to\repo`。
- 在 WSL 中，通常对应 `/mnt/d/path/to/repo`。
- 在 Windows 原生环境中，可以直接使用 `D:\path\to\repo`。
- `NODE_HOME` 必须指向实际包含 `node.exe` 的 Node 安装根。
- `DEVECO_SDK_HOME` 必须指向一个经 `hvigorw.bat tasks` 验证可工作的 SDK 根。
- `hvigorw.bat` 的常见路径是：
  - `C:\Program Files\Huawei\DevEco Studio\tools\hvigor\bin\hvigorw.bat`

## 探测策略

1. 先把仓库路径解析成 Windows 驱动器路径。
   - WSL 接受 `/mnt/d/...`
   - WSL 也接受 `D:\...`
   - Windows 原生接受 `D:\...`
2. 在 PowerShell 中用 Machine + User 环境重新拼装有效 `Path`。
3. 按以下顺序解析 Node：
   - `NODE_HOME`
   - `where.exe node`
   - 常见安装根 `C:\Program Files\nodejs`
4. 按以下顺序收集 SDK 候选根：
   - `DEVECO_SDK_HOME`
   - `C:\Program Files\Huawei\DevEco Studio\sdk`
   - `C:\Program Files\Huawei\DevEco Studio\sdk\default`
   - `%USERPROFILE%\AppData\Local\OpenHarmony\Sdk`
   - `%USERPROFILE%\AppData\Local\Huawei\Sdk`
5. 用 `hvigorw.bat tasks` 逐个 probe SDK 候选根，选出第一个真正可工作的值。

## 错误映射

### `NODE_HOME is not set and no 'node' command could be found in your PATH`

- 含义：当前 Windows 进程无法解析 Node。
- 处理：先检查当前进程实际读取到的用户环境，不要先改项目代码。

### `Invalid value of 'DEVECO_SDK_HOME' in the system environment path`

- 含义：当前进程读到了错误的 SDK 根。
- 处理：先复查进程内实际环境值；如果刚改过环境变量，优先重开终端再试。

### `SDK component missing`

- 含义：路径存在，但它不是当前构建可用的 SDK 根。
- 处理：不要继续猜测，直接用 `hvigorw.bat tasks` probe 候选根。

### `hvigor daemon failed to listen on the port`

- 一般不是阻塞根因。
- 只要后续退回 `no-daemon mode` 并成功构建，就不要把它判成失败原因。

## 结论输出规则

- 如果探测成功且 `verify` 成功，可以明确说 Windows 侧 preflight 或构建验证已通过。
- 如果探测成功但 `verify` 失败，直接报告 Windows 侧失败，不要替用户脑补原因。
- 如果探测阶段就无法解析有效的仓库 Windows 路径、Node、SDK 或 `hvigorw.bat`，要报告环境阻塞，而不是声称项目代码有问题。
