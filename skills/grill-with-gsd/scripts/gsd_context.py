#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


CONTEXT_RE = re.compile(r"^(?P<phase>\d{1,2})-CONTEXT\.md$")
PHASE_RE = re.compile(r"^(?:phase[-_ ]?)?(?P<phase>\d{1,2})$", re.IGNORECASE)
STATE_PHASE_RE = re.compile(r"\bPhase\s+(?P<phase>\d{1,2})\b", re.IGNORECASE)


def repo_path(value: str | None) -> Path:
    return Path(value or ".").expanduser().resolve()


def rel(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return str(path)


def normalize_phase(value: str) -> str | None:
    match = PHASE_RE.match(value.strip())
    if match is None:
        return None
    return f"{int(match.group('phase')):02d}"


def context_phase(path: Path) -> str | None:
    match = CONTEXT_RE.match(path.name)
    if match is None:
        return None
    return f"{int(match.group('phase')):02d}"


def is_gsd_context(repo: Path, path: Path) -> bool:
    if context_phase(path) is None:
        return False
    try:
        parts = path.resolve().relative_to(repo.resolve()).parts
    except ValueError:
        return False
    return len(parts) >= 4 and parts[0] == ".planning" and parts[1] == "phases"


def find_contexts(repo: Path) -> list[Path]:
    phases = repo / ".planning" / "phases"
    if not phases.exists():
        return []
    return sorted(path for path in phases.glob("*/*-CONTEXT.md") if is_gsd_context(repo, path))


def phase_from_state(repo: Path) -> str | None:
    state = repo / ".planning" / "STATE.md"
    if not state.exists():
        return None
    text = state.read_text(encoding="utf-8", errors="replace")
    match = STATE_PHASE_RE.search(text)
    if match is None:
        return None
    return f"{int(match.group('phase')):02d}"


def ok_payload(repo: Path, path: Path, reason: str) -> dict[str, Any]:
    phase = context_phase(path)
    return {
        "ok": True,
        "reason": reason,
        "repo": str(repo),
        "context_file": rel(repo, path),
        "phase": phase,
        "phase_dir": rel(repo, path.parent),
        "candidates": [],
    }


def error_payload(repo: Path, error: str, candidates: list[Path]) -> dict[str, Any]:
    return {
        "ok": False,
        "error": error,
        "repo": str(repo),
        "context_file": None,
        "phase": None,
        "phase_dir": None,
        "candidates": [rel(repo, path) for path in candidates],
    }


def resolve_path(repo: Path, value: str) -> dict[str, Any]:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo / path
    if not path.exists():
        return error_payload(repo, f"context file not found: {value}", [])
    if not path.is_file() or not is_gsd_context(repo, path):
        return error_payload(repo, f"not a GSD phase CONTEXT.md: {value}", [])
    return ok_payload(repo, path, "explicit-path")


def resolve_phase(repo: Path, phase: str, candidates: list[Path]) -> dict[str, Any]:
    normalized = normalize_phase(phase)
    if normalized is None:
        return error_payload(repo, f"invalid phase: {phase}", candidates)
    matches = [path for path in candidates if context_phase(path) == normalized]
    if len(matches) == 1:
        return ok_payload(repo, matches[0], "phase")
    if not matches:
        return error_payload(repo, f"no CONTEXT.md found for phase {normalized}", candidates)
    return error_payload(repo, f"multiple CONTEXT.md files found for phase {normalized}", matches)


def resolve(repo: Path, target: list[str]) -> dict[str, Any]:
    candidates = find_contexts(repo)
    if target:
        if target[0] == "phase":
            if len(target) != 2:
                return error_payload(repo, "usage for phase target: phase <number>", candidates)
            return resolve_phase(repo, target[1], candidates)
        if len(target) != 1:
            return error_payload(repo, "target must be empty, 'phase <number>', or one context path", candidates)
        normalized = normalize_phase(target[0])
        if normalized is not None:
            return resolve_phase(repo, normalized, candidates)
        return resolve_path(repo, target[0])

    if len(candidates) == 1:
        return ok_payload(repo, candidates[0], "single-context")

    state_phase = phase_from_state(repo)
    if state_phase is not None:
        matches = [path for path in candidates if context_phase(path) == state_phase]
        if len(matches) == 1:
            return ok_payload(repo, matches[0], "state-current-phase")

    if not candidates:
        return error_payload(repo, "no GSD phase CONTEXT.md files found", [])
    return error_payload(repo, "multiple GSD phase CONTEXT.md candidates; specify one", candidates)


def print_result(payload: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if payload["ok"]:
        print(payload["context_file"])
        return
    print(payload["error"], file=sys.stderr)
    for candidate in payload["candidates"]:
        print(f"- {candidate}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Locate a GSD phase CONTEXT.md for grill-with-gsd.")
    parser.add_argument("target", nargs="*", help="empty, 'phase <number>', a phase number, or a context path")
    parser.add_argument("--repo", default=".", help="repository root; defaults to current directory")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = repo_path(args.repo)
    payload = resolve(repo, args.target)
    print_result(payload, args.format)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
