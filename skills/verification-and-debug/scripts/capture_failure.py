#!/usr/bin/env python3

import argparse
import json
import subprocess
import time
from pathlib import Path


PATTERN_GROUPS = {
    "harmony-arkts": [
        "arkts",
        "ets-loader",
        "ets compiler",
        "ets: syntaxerror",
        "arkts compiler",
    ],
    "harmony-resource-module": [
        "module.json5",
        "resource not found",
        "resource reference",
        "invalid resource",
        "json5 parse",
        "parse json5",
    ],
    "harmony-hvigor": [
        "hvigor",
        "hvigorw",
        "hvigor error",
    ],
    "harmony-ohpm": [
        "ohpm",
        "oh-package.json5",
        "oh_modules",
    ],
    "harmony-hdc": [
        "hdc",
        "no connected device",
        "device not found",
        "install parse failed",
        "failed to install hap",
    ],
    "harmony-deveco-sdk": [
        "deveco_sdk_home",
        "deveco studio sdk",
        "openharmony sdk",
        "harmonyos sdk",
        "api version not found",
    ],
    "java-jdk-mismatch": [
        "invalid source release",
        "unsupported class file major version",
        "release version",
        "target release",
        "java.lang.unsupportedclassversionerror",
    ],
    "java-spring-context": [
        "failed to load applicationcontext",
        "applicationcontext failure threshold",
        "springapplication",
        "application run failed",
    ],
    "java-bean": [
        "beancreationexception",
        "unsatisfieddependencyexception",
        "no qualifying bean",
        "no such bean definition",
        "failed to instantiate",
    ],
    "java-profile-config": [
        "spring.profiles.active",
        "could not resolve placeholder",
        "failed to bind properties",
        "configurationproperties",
        "application.yml",
        "application.properties",
    ],
    "java-migration": [
        "flyway",
        "liquibase",
        "migration checksum",
        "schema migration",
        "database migration",
    ],
    "java-dependency-conflict": [
        "dependency convergence error",
        "could not resolve dependencies",
        "could not find artifact",
        "duplicate class",
        "dependency resolution failed",
    ],
    "react-typescript": [
        "ts2304",
        "ts2322",
        "ts2345",
        "is not assignable to type",
        "typescript error",
        "typecheck failed",
    ],
    "react-eslint": [
        "eslint",
        "react-hooks/rules-of-hooks",
        "jsx-a11y",
        "no-unused-vars",
        "exhaustive-deps",
    ],
    "react-build": [
        "vite",
        "next build",
        "next.js build",
        "failed to compile",
        "failed to load config from",
    ],
    "react-hydration": [
        "hydration failed",
        "does not match server-rendered html",
        "text content does not match server-rendered html",
        "server rendered html",
    ],
    "react-module-resolution": [
        "failed to resolve import",
        "vite:import-analysis",
        "module not found: can't resolve",
        "does not provide an export named",
        "cannot resolve module",
    ],
    "react-env-var": [
        "import.meta.env",
        "next_public",
        "process.env",
        "missing env",
        "environment variable",
    ],
    "react-playwright-timeout": [
        "timeouterror:",
        "timeout 30000ms exceeded",
        "expect(locator",
        "waiting for selector",
        "waiting for expect",
        "locator.click: timeout",
    ],
    "react-css-layout": [
        "tohavescreenshot",
        "screenshot mismatch",
        "visual regression",
        "layout shift",
        "computed style",
    ],
    "dependency": [
        "modulenotfounderror",
        "cannot find module",
        "no module named",
        "unresolved import",
        "missing package",
        "package not found",
    ],
    "environment": [
        "command not found",
        "is not recognized as an internal or external command",
        "node_home",
        "deveco_sdk_home",
        "no such file or directory",
        "executable file not found",
    ],
    "network": [
        "econnrefused",
        "connection refused",
        "timed out",
        "timeout",
        "temporary failure in name resolution",
        "name or service not known",
    ],
    "permission": [
        "permission denied",
        "permissionerror",
        "eacces",
        "operation not permitted",
    ],
    "config": [
        "invalid configuration",
        "invalid config",
        "unknown option",
        "missing required configuration",
        "missing required key",
    ],
    "build": [
        "syntaxerror",
        "compile error",
        "compilation failed",
        "type error",
        "build failed",
    ],
    "test": [
        "assertionerror",
        "expected",
        "failing",
        "not equal",
        "test failed",
    ],
}

CATEGORY_PRIORITY = {
    "harmony-resource-module": 0,
    "harmony-arkts": 1,
    "harmony-deveco-sdk": 2,
    "harmony-ohpm": 3,
    "harmony-hdc": 4,
    "harmony-hvigor": 5,
    "java-jdk-mismatch": 10,
    "java-bean": 11,
    "java-profile-config": 12,
    "java-migration": 13,
    "java-dependency-conflict": 14,
    "java-spring-context": 19,
    "react-hydration": 20,
    "react-typescript": 21,
    "react-eslint": 22,
    "react-module-resolution": 23,
    "react-env-var": 24,
    "react-playwright-timeout": 25,
    "react-css-layout": 26,
    "react-build": 27,
    "command-timeout": 40,
    "dependency": 50,
    "environment": 51,
    "network": 52,
    "permission": 53,
    "config": 54,
    "build": 55,
    "test": 56,
}

NEXT_STEPS = {
    "harmony-arkts": [
        "先定位第一处 ArkTS/ETS 编译错误，核对组件装饰器、状态变量、Builder 参数和类型声明。",
        "若涉及页面结构或导航，优先做源码级最小复现；必要时再升级到模块级 hvigor 编译验证。",
    ],
    "harmony-resource-module": [
        "核对 module.json5、resources 路径、资源名称、Ability 配置和引用方是否一致。",
        "先确认 JSON5 语法和资源文件存在，再检查打包或运行期资源解析。",
    ],
    "harmony-hvigor": [
        "先看 hvigor 输出中第一处真实错误，区分 ArkTS、依赖、资源接线还是构建配置问题。",
        "核对 NODE_HOME、DEVECO_SDK_HOME、SDK 组件和模块名是否与当前工程匹配。",
    ],
    "harmony-ohpm": [
        "检查 oh-package.json5、oh_modules、锁文件和 registry 配置是否同步。",
        "先用 ohpm 的最小安装/解析命令复现依赖问题，再回到完整构建。",
    ],
    "harmony-hdc": [
        "确认设备连接、授权状态、目标 ABI/API 和 HAP 安装前提。",
        "先用 hdc list targets / shell 等最小命令区分设备链路与应用包问题。",
    ],
    "harmony-deveco-sdk": [
        "确认 DevEco SDK 路径、API 版本、toolchains 和 build-tools 组件是否存在。",
        "优先修正环境基线，再重新执行原失败命令收集新的第一处错误。",
    ],
    "java-jdk-mismatch": [
        "核对本地、CI、Maven/Gradle toolchain 和项目声明的 Java 版本是否一致。",
        "先用 java -version 与构建工具版本输出确认环境，再决定改 toolchain 还是改源码目标版本。",
    ],
    "java-spring-context": [
        "缩小到失败的 Spring 测试或启动入口，先看 ApplicationContext 最内层 cause。",
        "区分 Bean 装配、profile/config、数据库迁移和外部服务前提，避免只修表层启动错误。",
    ],
    "java-bean": [
        "检查 Bean 条件、扫描路径、构造函数依赖和 mock/test slice 是否遗漏。",
        "优先解释缺失或冲突 Bean 的来源，再决定补配置、补 mock 还是调整装配。",
    ],
    "java-profile-config": [
        "打印或比对最终生效的 Spring profile、配置源、环境变量和默认值。",
        "确认是配置缺失、覆盖顺序错误，还是代码读取的 key/类型不匹配。",
    ],
    "java-migration": [
        "核对迁移脚本顺序、checksum、幂等性、回滚路径和历史数据边界。",
        "先在隔离数据库或测试容器中复现迁移，再判断修脚本还是修基线状态。",
    ],
    "java-dependency-conflict": [
        "用 Maven/Gradle dependency tree 定位冲突来源、传递依赖和版本约束。",
        "优先通过依赖约束或排除规则修根因，并确认锁文件/CI 环境同步。",
    ],
    "react-typescript": [
        "先运行最小 typecheck，定位第一处 TypeScript 真实错误和相关类型来源。",
        "确认是组件 props、API schema、泛型约束还是 tsconfig 路径导致的类型漂移。",
    ],
    "react-eslint": [
        "区分规则违反、自动修复项和真实行为风险，先处理会改变运行时或 hooks 顺序的问题。",
        "对 React hooks、a11y 和安全相关规则保留人工复查，不要只靠批量 fix。",
    ],
    "react-build": [
        "确认失败来自 Vite/Next 配置、插件、环境变量、SSR 边界还是产物优化。",
        "先用最小 build/typecheck 复现第一处错误，再回到完整流水线。",
    ],
    "react-hydration": [
        "检查 SSR 与客户端首屏渲染输入是否一致，包括时间、随机数、权限状态和浏览器专属 API。",
        "优先定位产生不同 HTML 的组件边界，再决定移动到 client-only 还是修数据来源。",
    ],
    "react-module-resolution": [
        "核对 import 路径、别名、exports 字段、文件大小写和 tsconfig/vite/next 解析配置。",
        "先用单个导入或构建入口复现，避免把模块解析问题误判为业务代码错误。",
    ],
    "react-env-var": [
        "确认环境变量是否存在、前缀是否符合 Vite/Next 暴露规则，以及构建时/运行时读取时机。",
        "不要在前端静默使用假默认值；缺失关键配置应显式失败。",
    ],
    "react-playwright-timeout": [
        "先保留截图/trace/失败前 DOM，判断是选择器错误、异步等待不足、网络慢还是真实 UI 回归。",
        "优先等待用户可见状态或网络完成条件，不要盲目增加超时时间。",
    ],
    "react-css-layout": [
        "对比失败截图、viewport、字体/资源加载和关键 CSS 变更，确认是否为真实视觉回归。",
        "优先修布局约束、响应式断点或设计系统变量，再更新基线截图。",
    ],
    "command-timeout": [
        "确认命令是否进入等待外部输入、长时间轮询、死锁或依赖服务无响应状态。",
        "用更小的子命令、调试日志或超时前状态采样定位卡住的具体阶段，不要把无输出超时当成未知失败。",
    ],
    "dependency": [
        "确认依赖是否已安装、锁文件是否同步、运行环境是否与项目声明一致。",
        "缩小到单个导入或单个测试，确认缺失依赖出现的最早位置。",
    ],
    "environment": [
        "确认命令、环境变量、工作目录和外部工具链路径是否正确。",
        "先用最小命令验证环境前提，再回到完整失败命令。",
    ],
    "network": [
        "确认依赖服务是否已启动、地址是否正确、是否存在代理或 DNS 问题。",
        "把网络请求独立成最小探测命令，区分服务端故障与客户端配置问题。",
    ],
    "permission": [
        "确认目标路径、端口或设备权限，并检查是否由沙箱、文件锁或只读目录导致。",
        "优先修正权限前提，不要在代码里吞掉权限错误。",
    ],
    "config": [
        "回看配置来源、默认值、环境变量和最近改动，确认是读取问题还是配置本身无效。",
        "先打印或比对最终生效配置，再决定修配置还是修调用方。",
    ],
    "build": [
        "先用最小编译或类型检查命令稳定复现，再定位到第一处真实报错。",
        "不要同时修改多处不确定代码；先修第一处编译阻塞。",
    ],
    "test": [
        "缩小到单个失败用例，确认是断言回归、测试数据漂移还是环境问题。",
        "优先解释断言为什么失败，再决定修实现还是修测试。",
    ],
    "unknown": [
        "补完整错误栈和失败前后的关键上下文，再判断问题位于哪一层。",
        "先避免继续猜修；增加必要观察点后重新复现。",
    ],
    "success": [
        "命令已成功执行，若用户仍反馈异常，需要继续核对预期结果与实际行为差异。",
    ],
}

PLAYWRIGHT_TIMEOUT_CATEGORY = "react-playwright-timeout"
REACT_BUILD_CATEGORY = "react-build"
PLAYWRIGHT_TIMEOUT_TERMS = (
    "timeouterror:",
    "timeout",
    "timed out",
    "exceeded",
)
PLAYWRIGHT_CONTEXT_PATTERNS = (
    "@playwright/test",
    "playwright test",
    "test timeout of",
    "expect(locator",
    "locator.",
    "locator(",
    "page.",
    "waiting for selector",
    "waiting for expect",
    "waiting for locator",
)
VITE_BUILD_CONTEXT_PATTERNS = (
    "vite build",
    "vite.config",
    "vite config",
    "building for production",
    "error during build",
    "failed to compile",
    "compile error",
    "compilation failed",
    "failed to load config from",
    "build failed",
)


def has_playwright_timeout_context(lowered_output: str) -> bool:
    has_timeout_signal = any(term in lowered_output for term in PLAYWRIGHT_TIMEOUT_TERMS)
    has_playwright_context = any(pattern in lowered_output for pattern in PLAYWRIGHT_CONTEXT_PATTERNS)
    return has_timeout_signal and has_playwright_context


def has_vite_build_context(lowered_output: str) -> bool:
    if "vite" not in lowered_output:
        return False
    return any(pattern in lowered_output for pattern in VITE_BUILD_CONTEXT_PATTERNS)


def should_accept_pattern(category: str, pattern: str, lowered_output: str) -> bool:
    if category == PLAYWRIGHT_TIMEOUT_CATEGORY:
        return has_playwright_timeout_context(lowered_output)
    if category == REACT_BUILD_CATEGORY and pattern == "vite":
        return has_vite_build_context(lowered_output)
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a command and capture structured failure context.")
    parser.add_argument("--cwd", default=".", help="Working directory for the command.")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout in seconds. Defaults to 300.")
    parser.add_argument("--tail-lines", type=int, default=20, help="How many lines of stdout/stderr to retain.")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format. Defaults to markdown.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run, prefixed by --.")
    return parser.parse_args()


def tail_lines(text: str, limit: int) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= limit:
        return lines
    return lines[-limit:]


def classify_failure_details(output_text: str, exit_code: int) -> dict:
    if exit_code == 0:
        return {"classification": "success", "signals": [], "secondary_matches": []}

    lowered = output_text.lower()
    matches: list[tuple[str, str]] = []
    for category, patterns in PATTERN_GROUPS.items():
        for pattern in patterns:
            if should_accept_pattern(category, pattern, lowered) and pattern in lowered:
                matches.append((category, pattern))
    if matches:
        grouped_matches: dict[str, set[str]] = {}
        for category, pattern in matches:
            grouped_matches.setdefault(category, set()).add(pattern)

        ordered_categories = sorted(
            grouped_matches,
            key=lambda category: (
                CATEGORY_PRIORITY.get(category, 99),
                sorted(grouped_matches[category])[0],
            ),
        )
        category = ordered_categories[0]
        secondary_matches = [
            {
                "classification": secondary_category,
                "signals": sorted(grouped_matches[secondary_category])[:6],
            }
            for secondary_category in ordered_categories[1:]
        ]
        return {
            "classification": category,
            "signals": sorted(grouped_matches[category])[:6],
            "secondary_matches": secondary_matches,
        }
    return {"classification": "unknown", "signals": [], "secondary_matches": []}


def classify_failure(output_text: str, exit_code: int) -> tuple[str, list[str]]:
    details = classify_failure_details(output_text, exit_code)
    return details["classification"], details["signals"]


def run_command(command: list[str], cwd: Path, timeout: int) -> tuple[subprocess.CompletedProcess, float]:
    started_at = time.monotonic()
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return result, time.monotonic() - started_at


def build_os_error_report(command: list[str], cwd: Path, timeout: int, line_limit: int, exc: OSError) -> dict:
    signal = None
    if isinstance(exc, FileNotFoundError):
        if not cwd.exists():
            signal = "missing_working_directory"
        else:
            signal = "missing_executable"
    error_text = str(exc)
    classification = classify_failure_details(error_text, getattr(exc, "errno", 1) or 1)
    category = classification["classification"]
    signals = classification["signals"]
    secondary_matches = classification["secondary_matches"]
    if signal:
        category = "environment"
        signals = [signal]
        secondary_matches = []
    return {
        "command": command,
        "cwd": str(cwd.resolve()),
        "timeout_seconds": timeout,
        "duration_seconds": 0.0,
        "success": False,
        "timed_out": False,
        "exit_code": getattr(exc, "errno", 1) or 1,
        "classification": category,
        "signals": signals,
        "secondary_matches": secondary_matches,
        "stdout_tail": [],
        "stderr_tail": tail_lines(error_text, line_limit),
        "next_steps": NEXT_STEPS.get(category, NEXT_STEPS["unknown"]),
    }


def build_report(command: list[str], cwd: Path, timeout: int, line_limit: int) -> dict:
    try:
        result, duration = run_command(command, cwd, timeout)
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        combined = "\n".join(part for part in [stdout, stderr] if part)
        classification = classify_failure_details(combined, 124)
        if classification["classification"] == "unknown":
            timeout_signal = "timeout_expired_no_output" if not combined.strip() else "timeout"
            classification = {
                "classification": "command-timeout",
                "signals": [timeout_signal],
                "secondary_matches": [],
            }
        return {
            "command": command,
            "cwd": str(cwd.resolve()),
            "timeout_seconds": timeout,
            "duration_seconds": round(float(timeout), 3),
            "success": False,
            "timed_out": True,
            "exit_code": 124,
            "classification": classification["classification"],
            "signals": classification["signals"],
            "secondary_matches": classification["secondary_matches"],
            "stdout_tail": tail_lines(stdout, line_limit),
            "stderr_tail": tail_lines(stderr, line_limit),
            "next_steps": NEXT_STEPS.get(classification["classification"], NEXT_STEPS["unknown"]),
        }
    except OSError as exc:
        return build_os_error_report(command, cwd, timeout, line_limit, exc)

    combined = "\n".join(part for part in [result.stdout, result.stderr] if part)
    classification = classify_failure_details(combined, result.returncode)
    return {
        "command": command,
        "cwd": str(cwd.resolve()),
        "timeout_seconds": timeout,
        "duration_seconds": round(duration, 3),
        "success": result.returncode == 0,
        "timed_out": timed_out,
        "exit_code": result.returncode,
        "classification": classification["classification"],
        "signals": classification["signals"],
        "secondary_matches": classification["secondary_matches"],
        "stdout_tail": tail_lines(result.stdout, line_limit),
        "stderr_tail": tail_lines(result.stderr, line_limit),
        "next_steps": NEXT_STEPS.get(classification["classification"], NEXT_STEPS["unknown"]),
    }


def render_markdown(report: dict) -> str:
    lines = [
        f"命令：{' '.join(report['command'])}",
        f"工作目录：{report['cwd']}",
        f"退出码：{report['exit_code']}",
        f"耗时：{report['duration_seconds']}s",
        f"是否超时：{'是' if report['timed_out'] else '否'}",
        f"分类：{report['classification']}",
        f"命中信号：{', '.join(report['signals']) or '未识别'}",
        "下一步建议：",
    ]
    for step in report["next_steps"]:
        lines.append(f"- {step}")
    if report.get("secondary_matches"):
        lines.append("次级命中：")
        for match in report["secondary_matches"]:
            signals = ", ".join(match.get("signals", [])) or "未识别"
            lines.append(f"- {match['classification']}: {signals}")
    lines.append("stderr 尾部：")
    if report["stderr_tail"]:
        for line in report["stderr_tail"]:
            lines.append(f"- {line}")
    else:
        lines.append("- 无")
    lines.append("stdout 尾部：")
    if report["stdout_tail"]:
        for line in report["stdout_tail"]:
            lines.append(f"- {line}")
    else:
        lines.append("- 无")
    return "\n".join(lines)


def cli_exit_code(report: dict) -> int:
    if report["success"]:
        return 0
    exit_code = report.get("exit_code")
    if isinstance(exit_code, int) and 1 <= exit_code <= 255:
        return exit_code
    return 1


def main() -> int:
    args = parse_args()
    if not args.command:
        raise SystemExit("No command provided. Use -- <cmd> [args...]")
    command = list(args.command)
    if command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("No command provided after --.")

    cwd = Path(args.cwd).resolve()
    report = build_report(command, cwd, args.timeout, args.tail_lines)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report))
    return cli_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
