# 常见失败模式

## 依赖

- 信号：`ModuleNotFoundError`、`cannot find module`、`unresolved import`
- 先看：锁文件、安装步骤、运行环境、解释器 / Node 版本

## 环境

- 信号：`command not found`、工具链环境变量缺失、可执行文件不存在
- 先看：工作目录、PATH、项目要求的外部工具、启动命令是否用错壳层

## 网络 / 外部服务

- 信号：`ECONNREFUSED`、DNS 失败、超时
- 先看：依赖服务是否启动、地址配置、代理、端口与网络隔离

## 命令超时 / 卡住

- 信号：命令级 `TimeoutExpired`、超时退出码 124，尤其是 stdout/stderr 无输出
- 先看：是否等待外部输入、依赖服务、长轮询、死锁或子进程未退出；先缩小到更小命令并采样超时前状态

## 权限

- 信号：`Permission denied`、`EACCES`
- 先看：文件权限、端口占用、只读目录、容器 / 沙箱约束

## 配置

- 信号：`invalid configuration`、`unknown option`、缺少必填 key
- 先看：最终生效配置、环境变量覆盖、默认值与配置层级

## 构建 / 编译

- 信号：`SyntaxError`、`compile error`、`type error`
- 先看：第一处真实报错、生成代码、工具链版本和增量缓存

## 测试

- 信号：`AssertionError`、快照不匹配、单测失败
- 先看：是实现回归、测试预期过期，还是环境/数据夹具漂移

## Harmony / OpenHarmony

- ArkTS：`ArkTS`、`ets-loader`、ETS 编译错误；先看第一处类型/语法/组件结构错误，若同时命中 `module.json5`、JSON5 或资源引用，优先按资源 / 模块问题处理
- hvigor：`hvigor`、`hvigorw`、构建任务失败；先区分 ArkTS、依赖、资源接线、SDK 环境还是构建配置
- ohpm：`ohpm`、`oh-package.json5`、`oh_modules`；先看依赖声明、锁文件和 registry
- hdc：`hdc`、设备未连接、HAP 安装失败；先验证设备授权、目标 API/ABI 和最小 hdc 命令
- DevEco SDK：`DEVECO_SDK_HOME`、SDK/API 版本缺失；先确认 SDK 路径、toolchains、build-tools 和 Node 基线
- 资源 / 模块：`module.json5`、`resources/`、JSON5 解析、资源引用失败；先核对路径、名称、Ability 和引用方同步

## Java / Spring

- Spring Context：`Failed to load ApplicationContext`、`Application run failed`；这是启动包装信号，若同时命中 Bean、profile/config、迁移或依赖冲突，优先按具体根因处理
- Bean 装配：`BeanCreationException`、`UnsatisfiedDependencyException`、`No qualifying bean`；先看扫描路径、条件 Bean、mock/test slice
- Profile / 配置：`spring.profiles.active`、placeholder、配置绑定失败；先比对最终生效配置、环境变量和默认值
- 数据迁移：Flyway、Liquibase、checksum、schema migration；先验证顺序、幂等性、回滚和历史数据边界
- JDK 不匹配：`invalid source release`、`UnsupportedClassVersionError`；先核对本地、CI 和 toolchain Java 版本
- Maven / Gradle 依赖冲突：dependency convergence、artifact resolve、duplicate class；先看 dependency tree 和版本约束

## React Web

- TypeScript：`TS2304`、`TS2322`、类型不兼容；先定位第一处类型来源和 schema/props 漂移
- ESLint：`eslint`、hooks、a11y、unused vars；先处理会影响运行时或 hooks 顺序的规则
- Vite / Next build：`vite` 需同时带有 build/config/compile 上下文，`next build`、`failed to compile`；先区分配置、插件、SSR 边界和环境变量
- Hydration：`Hydration failed`、server-rendered HTML 不一致；先找 SSR 与客户端首屏输入差异
- 模块解析：`failed to resolve import`、`Module not found: Can't resolve`；先核对别名、exports、文件大小写和 tsconfig
- 环境变量：`import.meta.env`、`NEXT_PUBLIC`、`process.env`；先确认构建时/运行时读取和前缀暴露规则
- Playwright 超时：`TimeoutError` 需同时带有 locator、expect、page、selector 等 Playwright 上下文；先保留截图/trace 并判断选择器、异步等待还是 UI 回归
- CSS / 布局回归：截图不匹配、visual regression、layout shift；先比对 viewport、字体资源和关键 CSS 变更
