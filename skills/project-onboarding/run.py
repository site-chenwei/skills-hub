#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent
COMMANDS = {
    "project_facts": SKILL_ROOT / "scripts" / "project_facts.py",
}


def print_usage() -> None:
    print("usage: run.py {project_facts} [args...]", file=sys.stderr)


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
