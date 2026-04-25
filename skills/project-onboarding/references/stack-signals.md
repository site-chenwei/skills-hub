# 技术栈信号

## HarmonyOS / OpenHarmony

- 强识别信号：`build-profile.json5`、`hvigorfile.*`、`oh-package.json5`、`AppScope/app.json5`、`module.json5`、`*.ets`
- 辅助目录：`entry/`、`feature/`、`resources/`，仅作为上下文信号，不单独判定为 Harmony 项目
- 优先补读：模块 `module.json5`、入口 Ability、页面 `pages/`、导航 / Tabs / Builder 相关代码、资源引用链路
- 风险信号：
  - `build-profile.json5`、`hvigorfile.*`、`oh-package.json5`、`module.json5`、`resources/`
  - 跨多个 `.ets` 的页面结构、导航层级、根节点、Builder / BuilderParam 变更
- 常见验证：
  - 小范围文案、样式、局部业务逻辑：源码级检查、单测或手工最小路径验证
  - 命中页面结构、资源、模块配置或构建链路：倾向模块级 hvigor 编译验证
  - 不因识别为 Harmony 项目就默认升级到整包构建

## Java / JVM

- 关键文件：`pom.xml`、`build.gradle*`、`settings.gradle*`、`application.yml` / `application.properties`
- 关键目录 / 文件：`src/main/java`、`src/test/java`、`controller/`、`service/`、`repository/`、`dto/`、`db/migration/`
- 优先补读：模块定义、profile、Spring Boot 配置、Controller/API、DTO、Service、Repository、migration
- 风险信号：
  - Controller/API/DTO/schema/migration/config 变更
  - Maven/Gradle 依赖、插件、profile、锁定策略或工具链变更
- 常见验证：
  - `./gradlew test`
  - `mvn test`
  - 接口、DTO、迁移或配置变更需补契约、迁移和边界验证

## React Web

- 关键文件：`package.json`、锁文件、`tsconfig.json`、`vite.config.*`、`next.config.*`、`remix.config.*`
- 关键目录 / 文件：`src/App.*`、`src/main.*`、`app/`、`pages/`、`routes/`、`.storybook/`
- 识别信号：`react` / `react-dom` / `next` / `@remix-run/react` / `@vitejs/plugin-react`、Vitest/Jest/Testing Library/Playwright/Cypress、Storybook
- 风险信号：
  - routing、SSR / data loading、API client、auth、schema、design-system
  - `package.json`、锁文件、构建配置
- 常见验证：
  - package scripts 中的 `test`
  - package scripts 中的 `lint`
  - package scripts 中的 `typecheck`
  - package scripts 中的 `build`，尤其适用于 routing / SSR / schema / design-system / package 变更

## Node / TypeScript

- 关键文件：`package.json`、锁文件、`tsconfig.json`
- 优先补读：脚本区、工作区配置、`src/`、`apps/`、`packages/`
- 常见验证：
  - `pnpm test` / `npm test` / `yarn test`
  - `pnpm run build` / `npm run build`

## Python

- 关键文件：`pyproject.toml`、`requirements*.txt`、`uv.lock`、`poetry.lock`
- 优先补读：`[project]`、`[tool.*]`、`tests/`、入口脚本
- 常见验证：
  - `<python_cmd> -m pytest`
  - `<python_cmd> -m ruff check .`

## Go

- 关键文件：`go.mod`、`go.sum`
- 优先补读：`cmd/`、`internal/`、`pkg/`
- 常见验证：
  - `go test ./...`

## Rust

- 关键文件：`Cargo.toml`、`Cargo.lock`
- 优先补读：workspace 成员、`src/main.rs`、`src/lib.rs`
- 常见验证：
  - `cargo test`
  - `cargo check`

## 其他 JVM

- 关键文件：`pom.xml`、`build.gradle*`
- 优先补读：模块定义、profile、插件配置、`src/main`、`src/test`
- 常见验证：
  - `mvn test`
  - `./gradlew test`

## 识别后仍要确认的点

- 锁文件与声明的包管理器是否一致
- 默认测试命令是否真的覆盖本次任务影响面
- 多应用 / 多包仓库里当前任务实际落在哪个子模块
- README 描述的启动方式是否仍与当前配置一致
