#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent
SCRIPT_PATH = SKILL_ROOT / "scripts" / "harmony_build.py"
COMMANDS = {
    "detect",
    "doctor",
    "recommend-task",
    "list-tasks",
    "verify",
    "build",
    "capture-logs",
    "print-env",
}


def print_usage() -> None:
    print(
        "usage: run.py {detect,doctor,recommend-task,list-tasks,verify,build,capture-logs,print-env} [args...]",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print_usage()
        return 0

    command = args[0]
    if command not in COMMANDS:
        print(f"unknown command: {command}", file=sys.stderr)
        print_usage()
        return 2

    return subprocess.run([sys.executable, str(SCRIPT_PATH), *args], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
