#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent
SEARCH_SCRIPT = SKILL_ROOT / "scripts" / "search_docs.py"
INIT_SCRIPT = SKILL_ROOT / "scripts" / "local_doc_init.py"
REINIT_SCRIPT = SKILL_ROOT / "scripts" / "build_docset_index.py"


def print_usage() -> None:
    print("usage: run.py {init,search,refresh,reinit} [args...]", file=sys.stderr)


def build_command(args: list[str]) -> list[str] | None:
    if not args:
        return None

    command = args[0]
    forwarded = args[1:]
    if command == "init":
        if "--skill-root" not in forwarded:
            forwarded = ["--skill-root", str(SKILL_ROOT), *forwarded]
        return [sys.executable, str(INIT_SCRIPT), *forwarded]
    if command == "search":
        return [sys.executable, str(SEARCH_SCRIPT), *forwarded]
    if command == "refresh":
        return [sys.executable, str(SEARCH_SCRIPT), "--rebuild-stale", *forwarded]
    if command == "reinit":
        if "--rebuild" not in forwarded:
            forwarded = [*forwarded, "--rebuild"]
        return [sys.executable, str(REINIT_SCRIPT), *forwarded]
    if command in {"-h", "--help"}:
        return []
    return [sys.executable, str(SEARCH_SCRIPT), *args]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = build_command(args)
    if command == []:
        print_usage()
        return 0
    if command is None:
        print_usage()
        return 2
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
