# 技术栈信号

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
  - `python3 -m pytest`
  - `python3 -m ruff check .`

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

## JVM

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
