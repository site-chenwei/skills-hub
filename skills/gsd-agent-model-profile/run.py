#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent
SCRIPT_PATH = SKILL_ROOT / "scripts" / "apply-gsd-agent-model-profile.sh"
COMMAND_FLAGS = {
    "apply": [],
    "dry-run": ["--dry-run"],
    "verify": ["--verify"],
}


def print_usage() -> None:
    print(
        "usage: run.py {apply,dry-run,verify} [--agents-dir DIR|DIR] [--agent NAME] [--model MODEL] [--effort medium|high|xhigh]",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print_usage()
        return 0

    command = args[0]
    if command not in COMMAND_FLAGS:
        print(f"unknown command: {command}", file=sys.stderr)
        print_usage()
        return 2

    forwarded = [*COMMAND_FLAGS[command], *args[1:]]
    return subprocess.run([str(SCRIPT_PATH), *forwarded], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
