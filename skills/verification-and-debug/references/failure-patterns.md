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
