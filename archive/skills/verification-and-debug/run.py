#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent
CAPTURE_FAILURE_SCRIPT = SKILL_ROOT / "scripts" / "capture_failure.py"
COMMANDS = {
    "capture_failure": CAPTURE_FAILURE_SCRIPT,
    "check": CAPTURE_FAILURE_SCRIPT,
    "triage": CAPTURE_FAILURE_SCRIPT,
}


def print_usage() -> None:
    print("usage: run.py {capture_failure|check|triage} [args...]", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print_usage()
        return 0

    command = args.pop(0)
    script = COMMANDS.get(command)
    if script is None:
        print(f"unknown command: {command}", file=sys.stderr)
        print_usage()
        return 2

    return subprocess.run([sys.executable, str(script), *args], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
