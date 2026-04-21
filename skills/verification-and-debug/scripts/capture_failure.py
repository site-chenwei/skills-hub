#!/usr/bin/env python3

import argparse
import json
import subprocess
import time
from pathlib import Path


PATTERN_GROUPS = {
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
    "dependency": 0,
    "environment": 1,
    "network": 2,
    "permission": 3,
    "config": 4,
    "build": 5,
    "test": 6,
}

NEXT_STEPS = {
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


def classify_failure(output_text: str, exit_code: int) -> tuple[str, list[str]]:
    if exit_code == 0:
        return "success", []

    lowered = output_text.lower()
    matches = []
    for category, patterns in PATTERN_GROUPS.items():
        for pattern in patterns:
            if pattern in lowered:
                matches.append((category, pattern))
    if matches:
        matches.sort(key=lambda item: (CATEGORY_PRIORITY.get(item[0], 99), item[1]))
        category = matches[0][0]
        signals = sorted({pattern for matched_category, pattern in matches if matched_category == category})
        return category, signals[:6]
    return "unknown", []


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
    category, signals = classify_failure(error_text, getattr(exc, "errno", 1) or 1)
    if signal:
        category = "environment"
        signals = [signal]
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
        category, signals = classify_failure(combined, 124)
        return {
            "command": command,
            "cwd": str(cwd.resolve()),
            "timeout_seconds": timeout,
            "duration_seconds": round(float(timeout), 3),
            "success": False,
            "timed_out": True,
            "exit_code": 124,
            "classification": category,
            "signals": signals or ["timeout"],
            "stdout_tail": tail_lines(stdout, line_limit),
            "stderr_tail": tail_lines(stderr, line_limit),
            "next_steps": NEXT_STEPS.get(category, NEXT_STEPS["unknown"]),
        }
    except OSError as exc:
        return build_os_error_report(command, cwd, timeout, line_limit, exc)

    combined = "\n".join(part for part in [result.stdout, result.stderr] if part)
    category, signals = classify_failure(combined, result.returncode)
    return {
        "command": command,
        "cwd": str(cwd.resolve()),
        "timeout_seconds": timeout,
        "duration_seconds": round(duration, 3),
        "success": result.returncode == 0,
        "timed_out": timed_out,
        "exit_code": result.returncode,
        "classification": category,
        "signals": signals,
        "stdout_tail": tail_lines(result.stdout, line_limit),
        "stderr_tail": tail_lines(result.stderr, line_limit),
        "next_steps": NEXT_STEPS.get(category, NEXT_STEPS["unknown"]),
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
