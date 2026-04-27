#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent
SEARCH_SCRIPT = SKILL_ROOT / "scripts" / "search_docs.py"
INIT_SCRIPT = SKILL_ROOT / "scripts" / "local_doc_init.py"
REINIT_SCRIPT = SKILL_ROOT / "scripts" / "build_docset_index.py"


def print_usage() -> None:
    print("usage: run.py {init,search,lookup,refresh,reinit,status,doctor} [args...]", file=sys.stderr)


def print_unknown_command(command: str) -> None:
    print(f"unknown command: {command}", file=sys.stderr)
    print_usage()


def has_option(args: list[str], option: str) -> bool:
    return any(arg == option or arg.startswith(f"{option}=") for arg in args)


def inject_hub_root_option(args: list[str]) -> list[str]:
    """Support documented positional hub-root while keeping local_doc_init strict."""
    if not args or has_option(args, "--hub-root"):
        return args

    forwarded: list[str] = []
    positional_hub_root: str | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--skill-root":
            forwarded.append(arg)
            if index + 1 < len(args):
                forwarded.append(args[index + 1])
                index += 2
                continue
        if arg.startswith("--skill-root="):
            forwarded.append(arg)
        elif positional_hub_root is None and not arg.startswith("-"):
            positional_hub_root = arg
        else:
            forwarded.append(arg)
        index += 1

    if positional_hub_root is None:
        return args
    return ["--hub-root", positional_hub_root, *forwarded]


def build_command(args: list[str]) -> list[str] | None:
    if not args:
        return None

    command = args[0]
    forwarded = args[1:]
    if command == "init":
        forwarded = inject_hub_root_option(forwarded)
        if "--skill-root" not in forwarded:
            forwarded = ["--skill-root", str(SKILL_ROOT), *forwarded]
        return [sys.executable, str(INIT_SCRIPT), *forwarded]
    if command == "search":
        return [sys.executable, str(SEARCH_SCRIPT), *forwarded]
    if command == "lookup":
        if not has_option(forwarded, "--json"):
            forwarded = ["--json", *forwarded]
        return [sys.executable, str(SEARCH_SCRIPT), *forwarded]
    if command == "refresh":
        return [sys.executable, str(SEARCH_SCRIPT), "--rebuild-stale", *forwarded]
    if command == "reinit":
        if "--rebuild" not in forwarded:
            forwarded = [*forwarded, "--rebuild"]
        if not has_option(forwarded, "--docset"):
            forwarded = [*forwarded, "--docset", "all"]
        return [sys.executable, str(REINIT_SCRIPT), *forwarded]
    if command in {"status", "doctor"}:
        return [sys.executable, str(SEARCH_SCRIPT), "--status", *forwarded]
    if command in {"-h", "--help"}:
        return []
    return None


def is_json_envelope(text: str) -> bool:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and {"ok", "partial", "failed", "results", "failed_docsets"} <= set(payload)


def lookup_failure_envelope(message: str) -> dict[str, object]:
    return {
        "ok": False,
        "partial": False,
        "failed": True,
        "hub_root": None,
        "searched_docsets": [],
        "results": [],
        "failed_docsets": [
            {
                "id": "",
                "reason": "lookup_failed",
                "message": message.strip() or "lookup failed before JSON output",
            }
        ],
    }


def run_lookup(command: list[str]) -> int:
    proc = subprocess.run(command, check=False, capture_output=True, text=True)
    if proc.returncode == 0 or is_json_envelope(proc.stdout):
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        return proc.returncode

    message = proc.stderr or proc.stdout
    print(json.dumps(lookup_failure_envelope(message), ensure_ascii=False, indent=2))
    return proc.returncode or 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = build_command(args)
    if command == []:
        print_usage()
        return 0
    if command is None:
        if args:
            print_unknown_command(args[0])
        else:
            print_usage()
        return 2
    if args and args[0] == "lookup":
        return run_lookup(command)
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
