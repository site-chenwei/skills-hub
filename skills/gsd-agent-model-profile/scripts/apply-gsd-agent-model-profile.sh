#!/usr/bin/env bash
set -euo pipefail

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "error: python3 or python is required" >&2
  exit 127
fi

exec "$PYTHON_BIN" - "$@" <<'PY'
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path


TARGET_MODEL = "gpt-5.5"
PROFILES: "OrderedDict[str, str]" = OrderedDict()

for name in [
    "gsd-assumptions-analyzer",
    "gsd-code-reviewer",
    "gsd-planner",
    "gsd-plan-checker",
    "gsd-roadmapper",
    "gsd-verifier",
    "gsd-security-auditor",
    "gsd-integration-checker",
    "gsd-eval-planner",
]:
    PROFILES[name] = "xhigh"

for name in [
    "gsd-advisor-researcher",
    "gsd-ai-researcher",
    "gsd-code-fixer",
    "gsd-debug-session-manager",
    "gsd-debugger",
    "gsd-doc-synthesizer",
    "gsd-doc-verifier",
    "gsd-doc-writer",
    "gsd-domain-researcher",
    "gsd-eval-auditor",
    "gsd-executor",
    "gsd-framework-selector",
    "gsd-nyquist-auditor",
    "gsd-phase-researcher",
    "gsd-project-researcher",
    "gsd-research-synthesizer",
    "gsd-ui-auditor",
    "gsd-ui-checker",
    "gsd-ui-researcher",
    "gsd-user-profiler",
]:
    PROFILES[name] = "high"

for name in [
    "gsd-codebase-mapper",
    "gsd-doc-classifier",
    "gsd-intel-updater",
    "gsd-pattern-mapper",
]:
    PROFILES[name] = "medium"


FIELD_PATTERN = re.compile(r"^\s*(model|model_reasoning_effort)\s*=\s*(.*?)\s*(?:#.*)?$")
TABLE_PATTERN = re.compile(r"^\s*\[")
VALID_EFFORTS = {"medium", "high", "xhigh"}


def default_agents_dir() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "agents"
    return Path.home() / ".codex" / "agents"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply or verify the standard GSD agent model profile.",
    )
    parser.add_argument("agents_dir_positional", nargs="?", help="custom agents directory")
    parser.add_argument("--agents-dir", dest="agents_dir_option", help="custom agents directory")
    parser.add_argument("--agent", help="target a single GSD agent name, for example gsd-code-reviewer")
    parser.add_argument("--model", default=TARGET_MODEL, help=f"target model for --agent mode; default: {TARGET_MODEL}")
    parser.add_argument("--effort", choices=sorted(VALID_EFFORTS), help="target reasoning effort for --agent mode")
    parser.add_argument("--dry-run", action="store_true", help="show intended changes without writing")
    parser.add_argument("--verify", action="store_true", help="verify all target agents are configured")
    args = parser.parse_args(argv)

    if args.agents_dir_positional and args.agents_dir_option:
        parser.error("use either positional agents_dir or --agents-dir, not both")
    if args.dry_run and args.verify:
        parser.error("--dry-run and --verify are mutually exclusive")
    if args.agent and args.agent not in PROFILES:
        parser.error(f"unknown GSD agent: {args.agent}")
    if not args.agent and args.effort:
        parser.error("--effort requires --agent")
    if not args.agent and args.model != TARGET_MODEL:
        parser.error("--model requires --agent")
    return args


def update_multiline_state(line: str, current: str | None) -> str | None:
    if current is not None:
        return None if line.count(current) % 2 == 1 else current

    candidates = [(line.find("'''"), "'''"), (line.find('"""'), '"""')]
    candidates = [candidate for candidate in candidates if candidate[0] != -1]
    if not candidates:
        return None

    _, delimiter = min(candidates, key=lambda candidate: candidate[0])
    return delimiter if line.count(delimiter) % 2 == 1 else None


def split_toml_string(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def top_level_fields(text: str) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {"model": [], "model_reasoning_effort": []}
    multiline_delimiter: str | None = None
    table_seen = False

    for line in text.splitlines():
        if multiline_delimiter is None:
            if TABLE_PATTERN.match(line):
                table_seen = True
            if not table_seen:
                match = FIELD_PATTERN.match(line)
                if match:
                    fields[match.group(1)].append(split_toml_string(match.group(2)))

        multiline_delimiter = update_multiline_state(line, multiline_delimiter)

    return fields


def render_profile(text: str, model: str, effort: str) -> str:
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    multiline_delimiter: str | None = None
    table_seen = False

    for line in lines:
        should_skip = False
        if multiline_delimiter is None:
            if TABLE_PATTERN.match(line):
                table_seen = True
            if not table_seen and FIELD_PATTERN.match(line):
                should_skip = True

        if not should_skip:
            output.append(line)
        multiline_delimiter = update_multiline_state(line, multiline_delimiter)

    prefix = f'model = "{model}"\nmodel_reasoning_effort = "{effort}"\n'
    return prefix + "".join(output)


def verify_text(text: str, model: str, effort: str) -> tuple[bool, str]:
    fields = top_level_fields(text)
    expected = {"model": model, "model_reasoning_effort": effort}
    problems: list[str] = []

    for field, expected_value in expected.items():
        actual_values = fields[field]
        if actual_values != [expected_value]:
            actual = ", ".join(actual_values) if actual_values else "<missing>"
            problems.append(f"{field} expected {expected_value}, actual {actual}")

    return not problems, "; ".join(problems)


def resolve_agents_dir(args: argparse.Namespace) -> Path:
    value = args.agents_dir_option or args.agents_dir_positional
    return Path(value).expanduser() if value else default_agents_dir()


def target_profiles(args: argparse.Namespace) -> "OrderedDict[str, tuple[str, str]]":
    if args.agent:
        return OrderedDict([(args.agent, (args.model, args.effort or PROFILES[args.agent]))])
    return OrderedDict((agent_name, (TARGET_MODEL, effort)) for agent_name, effort in PROFILES.items())


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    agents_dir = resolve_agents_dir(args)
    profiles = target_profiles(args)
    missing: list[Path] = []
    failed: list[str] = []
    changed = 0
    checked = 0

    for agent_name, (model, effort) in profiles.items():
        path = agents_dir / f"{agent_name}.toml"
        checked += 1
        if not path.exists():
            missing.append(path)
            print(f"MISSING {path}", file=sys.stderr)
            continue

        original = path.read_text(encoding="utf-8")
        if args.verify:
            ok, reason = verify_text(original, model, effort)
            if ok:
                print(f"OK {path}")
            else:
                failed.append(f"{path}: {reason}")
                print(f"FAIL {path}: {reason}", file=sys.stderr)
            continue

        desired = render_profile(original, model, effort)
        if args.dry_run:
            if desired == original:
                print(f"OK {path} model={model} model_reasoning_effort={effort}")
            else:
                print(f"WOULD_UPDATE {path} model={model} model_reasoning_effort={effort}")
            continue

        if desired == original:
            print(f"OK {path}")
            continue

        path.write_text(desired, encoding="utf-8")
        changed += 1
        print(f"UPDATED {path} model={model} model_reasoning_effort={effort}")

    if missing:
        print("missing agents:", file=sys.stderr)
        for path in missing:
            print(f"- {path}", file=sys.stderr)

    if failed:
        print("profile mismatches:", file=sys.stderr)
        for item in failed:
            print(f"- {item}", file=sys.stderr)

    print(
        f"SUMMARY checked={checked} changed={changed} missing={len(missing)} failed={len(failed)}"
    )
    return 1 if missing or failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
PY
