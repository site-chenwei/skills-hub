# 结构化开发触发与输出

## 默认触发判断

- 单文件、小修复、无接口或依赖变更：
  可以走轻量模式，但保留验证。
- 多文件且边界清晰、低风险、可快速验证：
  可以折叠显示流程，但仍要做复查和验证。
- 其余复杂任务：
  启用完整结构化流程。

## Light 模式退出条件

- 已确认目标、边界和验证命令
- 涉及文件少、模块少，不牵涉接口、依赖、schema 或高风险配置
- 变更可以通过单次最小充分验证覆盖主要风险

## Full 模式触发器

- 接口、配置、schema、迁移或依赖变更
- 多模块、多应用或跨层调用链调整
- 安全、性能、稳定性相关改动
- 用户明确要求先给方案或需要可审计的阶段输出

## 技术栈高风险路径

- HarmonyOS / OpenHarmony：
  - `.ets` 页面结构、导航层级、根节点、Builder / BuilderParam、Tabs / Navigation 相关变更
  - `build-profile.json5`、`hvigorfile.*`、`oh-package.json5`、`module.json5`、`resources/`
  - 验证优先级：小改先源码级 / 手工最小路径；命中上述高风险点时倾向模块级 hvigor 编译，不默认整包构建
- Java / JVM：
  - controller、api、dto、schema、migration、config、dependency
  - 验证优先级：受影响模块的 `./gradlew test` 或 `mvn test`；接口、DTO、迁移和配置变更补契约 / 数据边界验证
- React Web：
  - routing、SSR / data loading、API client、auth、schema、design-system、package / lockfile
  - 验证优先级：相关 package scripts 的 `test`、`lint`、`typecheck`；路由、SSR、schema、design-system、依赖变更按风险补 `build`

## 阶段门禁

- Research 完成：
  目标、边界、验证路径、约束已明确
- Design 完成：
  推荐方案、关键取舍、影响面和失败条件已明确
- Implement 完成：
  最小闭环改动已落地，无顺手重构
- Review 完成：
  回归、契约、异常处理、测试缺口已独立复看
- Verify 完成：
  最小充分验证已执行，必要时扩大验证范围

## 推荐输出骨架

- 结论 / 推荐方案：
- 关键取舍：
- 涉及文件 / 模块：
- 实施步骤：
- 复查重点：
- 验证命令：
- 剩余风险：
