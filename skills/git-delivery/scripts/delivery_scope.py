#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


SYSTEM_ARTIFACT_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
DIAGNOSTIC_MARKERS = ("appfreeze", "crash", "hilog", "trace", "diagnostic")
SECRET_MARKERS = (".env", "secret", "token", "credential", "credentials", "id_rsa")
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
GENERATED_MARKERS = (
    "BuildProfile.ets",
    ".hvigor/",
    "oh_modules/",
    "node_modules/",
    ".pytest_cache/",
    "__pycache__/",
    "dist/",
    "build/",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize Git delivery scope and preflight risks.")
    parser.add_argument("--repo", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser.parse_args()


def run_git(repo: Path, args: list[str]) -> dict[str, object]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def parse_status_line(line: str) -> dict[str, str]:
    if line.startswith("## "):
        return {"kind": "branch", "status": "##", "path": line[3:].strip()}
    if line.startswith("?? "):
        return {"kind": "untracked", "status": "??", "path": line[3:].strip()}
    if len(line) >= 4:
        return {"kind": "tracked", "status": line[:2], "path": line[3:].strip()}
    return {"kind": "unknown", "status": "", "path": line.strip()}


def path_flags(path: str) -> list[str]:
    normalized = path.replace("\\", "/")
    name = Path(normalized).name
    lowered = normalized.lower()
    flags: list[str] = []
    if name in SYSTEM_ARTIFACT_NAMES:
        flags.append("system-artifact")
    if any(marker in lowered for marker in DIAGNOSTIC_MARKERS) or lowered.endswith((".log", ".trace")):
        flags.append("diagnostic-artifact")
    if any(marker in lowered for marker in SECRET_MARKERS) or lowered.endswith(SECRET_SUFFIXES):
        flags.append("secret-risk")
    if any(marker.lower() in lowered for marker in GENERATED_MARKERS):
        flags.append("generated-artifact")
    return flags


def collect_summary(repo: Path) -> dict[str, object]:
    canonical_repo = repo.expanduser().resolve()
    root_result = run_git(canonical_repo, ["rev-parse", "--show-toplevel"])
    if not root_result["ok"]:
        return {
            "ok": False,
            "repo": str(canonical_repo),
            "error": root_result["stderr"] or root_result["stdout"],
        }

    git_root = Path(str(root_result["stdout"])).resolve()
    status_result = run_git(git_root, ["status", "--short", "--branch"])
    branch_result = run_git(git_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    upstream_result = run_git(git_root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    diff_check = run_git(git_root, ["diff", "--check"])
    cached_diff_check = run_git(git_root, ["diff", "--cached", "--check"])

    upstream = str(upstream_result["stdout"]) if upstream_result["ok"] else ""
    ahead_behind = None
    if upstream:
        ahead_result = run_git(git_root, ["rev-list", "--left-right", "--count", "HEAD...@{u}"])
        if ahead_result["ok"]:
            parts = str(ahead_result["stdout"]).split()
            if len(parts) == 2:
                ahead_behind = {"ahead": int(parts[0]), "behind": int(parts[1])}

    entries = []
    attention = []
    for line in str(status_result["stdout"]).splitlines():
        item = parse_status_line(line)
        if item["kind"] == "branch":
            continue
        flags = path_flags(item["path"])
        item["flags"] = flags
        entries.append(item)
        if flags:
            attention.append(item)

    if not diff_check["ok"]:
        attention.append(
            {
                "kind": "check",
                "status": "!!",
                "path": "git diff --check",
                "flags": ["diff-check-failed"],
                "message": diff_check["stdout"] or diff_check["stderr"],
            }
        )
    if not cached_diff_check["ok"]:
        attention.append(
            {
                "kind": "check",
                "status": "!!",
                "path": "git diff --cached --check",
                "flags": ["diff-cached-check-failed"],
                "message": cached_diff_check["stdout"] or cached_diff_check["stderr"],
            }
        )

    return {
        "ok": True,
        "repo": str(git_root),
        "branch": branch_result["stdout"] if branch_result["ok"] else "",
        "upstream": upstream,
        "ahead_behind": ahead_behind,
        "status_clean": not entries,
        "entries": entries,
        "attention": attention,
        "checks": {
            "git_diff_check": {
                "ok": diff_check["ok"],
                "returncode": diff_check["returncode"],
                "output": diff_check["stdout"] or diff_check["stderr"],
            },
            "git_diff_cached_check": {
                "ok": cached_diff_check["ok"],
                "returncode": cached_diff_check["returncode"],
                "output": cached_diff_check["stdout"] or cached_diff_check["stderr"],
            }
        },
    }


def format_markdown(summary: dict[str, object]) -> str:
    if not summary.get("ok"):
        return f"Git 交付范围检查失败：{summary.get('error', 'unknown error')}\n"

    lines = [
        f"仓库路径：{summary['repo']}",
        f"分支：{summary.get('branch') or 'unknown'}",
        f"Upstream：{summary.get('upstream') or '未设置'}",
    ]
    ahead_behind = summary.get("ahead_behind")
    if isinstance(ahead_behind, dict):
        lines.append(f"Ahead/Behind：{ahead_behind['ahead']} / {ahead_behind['behind']}")
    lines.append(f"工作区：{'clean' if summary.get('status_clean') else 'dirty'}")
    lines.append("")
    lines.append("变更文件：")
    entries = summary.get("entries") or []
    if entries:
        for item in entries:
            flags = ",".join(item.get("flags") or [])
            suffix = f" [{flags}]" if flags else ""
            lines.append(f"- {item['status']} {item['path']}{suffix}")
    else:
        lines.append("- 无")
    lines.append("")
    lines.append("注意事项：")
    attention = summary.get("attention") or []
    if attention:
        for item in attention:
            flags = ",".join(item.get("flags") or [])
            message = item.get("message")
            lines.append(f"- {item['path']}：{flags or 'needs-review'}")
            if message:
                lines.append(f"  {message}")
    else:
        lines.append("- 未识别到系统文件、诊断日志、凭据风险或 diff --check 问题。")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    summary = collect_summary(Path(args.repo))
    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(summary), end="")
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
