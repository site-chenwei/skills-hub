#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent
SCRIPT_PATH = SKILL_ROOT / "scripts" / "delivery_scope.py"
COMMANDS = {
    "delivery-scope": (SCRIPT_PATH, []),
    "preflight": (SCRIPT_PATH, ["--mode", "preflight"]),
    "stage-plan": (SCRIPT_PATH, ["--mode", "stage-plan"]),
    "commit-plan": (SCRIPT_PATH, ["--mode", "commit-plan"]),
    "post-push-check": (SCRIPT_PATH, ["--mode", "post-push-check"]),
}


def print_usage() -> None:
    commands = "|".join(COMMANDS)
    print(f"usage: run.py {{{commands}}} [args...]", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print_usage()
        return 0

    command = args.pop(0)
    command_config = COMMANDS.get(command)
    if command_config is None:
        print(f"unknown command: {command}", file=sys.stderr)
        print_usage()
        return 2
    script, injected_args = command_config
    return subprocess.run([sys.executable, str(script), *injected_args, *args], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
