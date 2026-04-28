#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


SCHEMA_VERSION = 1
SYSTEM_ARTIFACT_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
DIAGNOSTIC_MARKERS = ("appfreeze", "crash", "hilog", "trace", "diagnostic")
SECRET_MARKERS = (".env", "secret", "token", "credential", "credentials", "id_rsa")
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
MERGE_CONFLICT_STATUSES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
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
    parser.add_argument(
        "--mode",
        choices=("delivery-scope", "preflight", "stage-plan", "commit-plan", "post-push-check"),
        default="delivery-scope",
        help="Report mode. Defaults to delivery-scope.",
    )
    parser.add_argument("--repo", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--expected-branch", help="Expected local branch for post-push-check.")
    parser.add_argument("--expected-commit", help="Expected commit for post-push-check.")
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


def status_flags(status: str) -> list[str]:
    flags: list[str] = []
    if status in MERGE_CONFLICT_STATUSES or "U" in status:
        flags.append("merge-conflict")
    return flags


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


def merge_flags(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for flag in group:
            if flag not in merged:
                merged.append(flag)
    return merged


def is_staged(item: dict[str, object]) -> bool:
    status = str(item.get("status", ""))
    return item.get("kind") == "tracked" and bool(status) and status[0] not in {" ", "?"}


def is_unstaged(item: dict[str, object]) -> bool:
    status = str(item.get("status", ""))
    return item.get("kind") in {"tracked", "untracked"} and (
        item.get("kind") == "untracked" or (len(status) > 1 and status[1] not in {" ", "?"})
    )


def issue(issue_id: str, severity: str, message: str, *, path: str = "", evidence: str = "") -> dict[str, object]:
    return {
        "id": issue_id,
        "severity": severity,
        "blocking": severity == "blocker",
        "path": path,
        "message": message,
        "evidence": evidence,
    }


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
        flags = merge_flags(path_flags(item["path"]), status_flags(item["status"]))
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
        "schema_version": SCHEMA_VERSION,
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


def classify_issues(summary: dict[str, object], *, include_upstream: bool) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    blockers: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []

    for item in summary.get("attention") or []:
        flags = item.get("flags") or []
        path = str(item.get("path") or "")
        message = str(item.get("message") or "")
        if "secret-risk" in flags:
            blockers.append(issue("secret-risk", "blocker", "credential-like file requires explicit handling", path=path))
        if "merge-conflict" in flags:
            blockers.append(issue("merge-conflict", "blocker", "merge conflict must be resolved before delivery", path=path))
        if "diff-check-failed" in flags:
            blockers.append(issue("diff-check-failed", "blocker", "unstaged diff hygiene check failed", path=path, evidence=message))
        if "diff-cached-check-failed" in flags:
            blockers.append(issue("diff-cached-check-failed", "blocker", "staged diff hygiene check failed", path=path, evidence=message))
        if "system-artifact" in flags:
            warnings.append(issue("system-artifact", "warning", "system artifact should normally stay out of commits", path=path))
        if "diagnostic-artifact" in flags:
            warnings.append(issue("diagnostic-artifact", "warning", "diagnostic artifact should normally stay out of commits", path=path))
        if "generated-artifact" in flags:
            warnings.append(issue("generated-artifact", "warning", "generated artifact needs explicit review before commit", path=path))

    if include_upstream:
        if not summary.get("upstream"):
            blockers.append(issue("upstream-missing", "blocker", "upstream is not configured; push target must be explicit"))
        ahead_behind = summary.get("ahead_behind")
        if isinstance(ahead_behind, dict) and int(ahead_behind.get("behind", 0)) > 0:
            blockers.append(issue("upstream-behind", "blocker", "local branch is behind upstream; reconcile before delivery"))

    return blockers, warnings


def build_preflight(summary: dict[str, object]) -> dict[str, object]:
    blockers, warnings = classify_issues(summary, include_upstream=True)
    entries = summary.get("entries") or []
    checks = [
        {
            "id": "git_diff_check",
            "ok": summary["checks"]["git_diff_check"]["ok"],
            "blocking": not summary["checks"]["git_diff_check"]["ok"],
            "output": summary["checks"]["git_diff_check"]["output"],
        },
        {
            "id": "git_diff_cached_check",
            "ok": summary["checks"]["git_diff_cached_check"]["ok"],
            "blocking": not summary["checks"]["git_diff_cached_check"]["ok"],
            "output": summary["checks"]["git_diff_cached_check"]["output"],
        },
    ]
    return {
        "ok": not blockers,
        "schema_version": SCHEMA_VERSION,
        "repo": summary["repo"],
        "branch": summary.get("branch"),
        "upstream": summary.get("upstream"),
        "ahead_behind": summary.get("ahead_behind"),
        "status_clean": summary.get("status_clean"),
        "summary": {
            "changed_files": len(entries),
            "staged_files": sum(1 for item in entries if is_staged(item)),
            "unstaged_or_untracked_files": sum(1 for item in entries if is_unstaged(item)),
            "blockers": len(blockers),
            "warnings": len(warnings),
        },
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
    }


def stage_recommendation(item: dict[str, object]) -> tuple[str, str]:
    flags = item.get("flags") or []
    if "secret-risk" in flags:
        return "block", "credential-like path requires explicit handling"
    if "merge-conflict" in flags:
        return "block", "merge conflict must be resolved first"
    if any(flag in flags for flag in ("system-artifact", "diagnostic-artifact", "generated-artifact")):
        return "exclude", "local/generated artifact should not be staged by default"
    if item.get("kind") == "untracked":
        return "needs-review", "untracked file needs explicit inclusion decision"
    return "stage", "tracked source change looks stageable"


def build_stage_plan(summary: dict[str, object]) -> dict[str, object]:
    blockers, warnings = classify_issues(summary, include_upstream=False)
    files = []
    for item in summary.get("entries") or []:
        action, reason = stage_recommendation(item)
        files.append(
            {
                "path": item.get("path"),
                "status": item.get("status"),
                "kind": item.get("kind"),
                "flags": item.get("flags") or [],
                "recommended_action": action,
                "reason": reason,
            }
        )
    return {
        "ok": not blockers,
        "schema_version": SCHEMA_VERSION,
        "repo": summary["repo"],
        "files": files,
        "blockers": blockers,
        "warnings": warnings,
        "commands": {
            "note": "stage-plan is read-only; review paths before running explicit git add commands",
            "stageable_paths": [item["path"] for item in files if item["recommended_action"] == "stage"],
        },
    }


def staged_entries(summary: dict[str, object]) -> list[dict[str, object]]:
    return [item for item in summary.get("entries") or [] if is_staged(item)]


def suggest_commit_message(entries: list[dict[str, object]]) -> str:
    paths = [str(item.get("path") or "") for item in entries]
    if not paths:
        return ""
    top_dirs = {path.split("/", 1)[0] for path in paths if path}
    if len(top_dirs) == 1 and "skills" in top_dirs:
        skill_names = sorted({path.split("/")[1] for path in paths if path.startswith("skills/") and len(path.split("/")) > 1})
        if len(skill_names) == 1:
            return f"更新 {skill_names[0]} 交付能力"
        return "完善 Skill 交付能力"
    return "提交当前变更"


def build_commit_plan(summary: dict[str, object]) -> dict[str, object]:
    blockers, warnings = classify_issues(summary, include_upstream=False)
    entries = staged_entries(summary)
    staged_flags = {flag for item in entries for flag in item.get("flags", [])}
    if not entries:
        blockers.append(issue("no-staged-changes", "blocker", "no staged changes are available for commit"))
    if "secret-risk" in staged_flags:
        blockers.append(issue("staged-secret-risk", "blocker", "staged credential-like path requires explicit handling"))
    diffstat = run_git(Path(str(summary["repo"])), ["diff", "--cached", "--stat"])
    names = run_git(Path(str(summary["repo"])), ["diff", "--cached", "--name-only"])
    return {
        "ok": not blockers,
        "schema_version": SCHEMA_VERSION,
        "repo": summary["repo"],
        "staged_files": [item.get("path") for item in entries],
        "suggested_message": suggest_commit_message(entries),
        "diffstat": diffstat["stdout"] if diffstat["ok"] else "",
        "name_only": str(names["stdout"]).splitlines() if names["ok"] and names["stdout"] else [],
        "checks": {
            "git_diff_cached_check": summary["checks"]["git_diff_cached_check"],
        },
        "blockers": blockers,
        "warnings": warnings,
        "validation_hints": [
            "run git diff --cached --check before committing",
            "run the smallest validation command that supports the delivery claim",
        ],
    }


def build_post_push_check(
    summary: dict[str, object],
    *,
    expected_branch: str | None,
    expected_commit: str | None,
) -> dict[str, object]:
    blockers, warnings = classify_issues(summary, include_upstream=True)
    ahead_behind = summary.get("ahead_behind")
    synced = isinstance(ahead_behind, dict) and ahead_behind.get("ahead") == 0 and ahead_behind.get("behind") == 0
    if not synced:
        blockers.append(issue("upstream-not-synced", "blocker", "local branch is not synchronized with upstream"))
    if not summary.get("status_clean"):
        warnings.append(issue("worktree-dirty", "warning", "worktree still has local changes after push check"))
    if expected_branch and summary.get("branch") != expected_branch:
        blockers.append(issue("branch-mismatch", "blocker", f"current branch does not match expected branch {expected_branch}"))

    expected_commit_result = None
    remote_contains_expected_commit = None
    if expected_commit:
        expected_commit_result = run_git(Path(str(summary["repo"])), ["rev-parse", "--verify", expected_commit])
        if expected_commit_result["ok"] and summary.get("upstream"):
            remote_contains = run_git(
                Path(str(summary["repo"])),
                ["merge-base", "--is-ancestor", str(expected_commit_result["stdout"]), "@{u}"],
            )
            remote_contains_expected_commit = remote_contains["ok"]
            if not remote_contains_expected_commit:
                blockers.append(issue("expected-commit-not-upstream", "blocker", "expected commit is not contained in upstream"))
        else:
            blockers.append(issue("expected-commit-invalid", "blocker", "expected commit could not be resolved"))

    return {
        "ok": not blockers,
        "schema_version": SCHEMA_VERSION,
        "repo": summary["repo"],
        "branch": summary.get("branch"),
        "upstream": summary.get("upstream"),
        "ahead_behind": ahead_behind,
        "status_clean": summary.get("status_clean"),
        "synced": synced,
        "expected_branch": expected_branch,
        "expected_commit": expected_commit,
        "remote_contains_expected_commit": remote_contains_expected_commit,
        "blockers": blockers,
        "warnings": warnings,
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


def format_issues(blockers: list[dict[str, object]], warnings: list[dict[str, object]]) -> list[str]:
    lines = ["Blockers："]
    if blockers:
        lines.extend(f"- {item['id']}: {item['message']} {item.get('path') or ''}".rstrip() for item in blockers)
    else:
        lines.append("- 无")
    lines.append("Warnings：")
    if warnings:
        lines.extend(f"- {item['id']}: {item['message']} {item.get('path') or ''}".rstrip() for item in warnings)
    else:
        lines.append("- 无")
    return lines


def format_preflight(payload: dict[str, object]) -> str:
    lines = [
        f"仓库路径：{payload['repo']}",
        f"分支：{payload.get('branch') or 'unknown'}",
        f"Upstream：{payload.get('upstream') or '未设置'}",
        f"Preflight：{'OK' if payload.get('ok') else 'BLOCKED'}",
        "",
        "摘要：",
    ]
    summary = payload.get("summary") or {}
    for key in ("changed_files", "staged_files", "unstaged_or_untracked_files", "blockers", "warnings"):
        lines.append(f"- {key}: {summary.get(key)}")
    lines.append("")
    lines.extend(format_issues(payload.get("blockers") or [], payload.get("warnings") or []))
    return "\n".join(lines) + "\n"


def format_stage_plan(payload: dict[str, object]) -> str:
    lines = [f"仓库路径：{payload['repo']}", "Stage Plan："]
    files = payload.get("files") or []
    if files:
        for item in files:
            flags = ",".join(item.get("flags") or [])
            suffix = f" [{flags}]" if flags else ""
            lines.append(f"- {item['recommended_action']} {item['status']} {item['path']}{suffix}：{item['reason']}")
    else:
        lines.append("- 无变更")
    lines.append("")
    lines.extend(format_issues(payload.get("blockers") or [], payload.get("warnings") or []))
    return "\n".join(lines) + "\n"


def format_commit_plan(payload: dict[str, object]) -> str:
    lines = [
        f"仓库路径：{payload['repo']}",
        f"Commit Plan：{'OK' if payload.get('ok') else 'BLOCKED'}",
        f"建议提交信息：{payload.get('suggested_message') or '无'}",
        "",
        "Staged files：",
    ]
    staged = payload.get("staged_files") or []
    lines.extend(f"- {path}" for path in staged) if staged else lines.append("- 无")
    if payload.get("diffstat"):
        lines.extend(["", "Diffstat：", str(payload["diffstat"])])
    lines.append("")
    lines.extend(format_issues(payload.get("blockers") or [], payload.get("warnings") or []))
    return "\n".join(lines) + "\n"


def format_post_push_check(payload: dict[str, object]) -> str:
    lines = [
        f"仓库路径：{payload['repo']}",
        f"分支：{payload.get('branch') or 'unknown'}",
        f"Upstream：{payload.get('upstream') or '未设置'}",
        f"Post Push：{'OK' if payload.get('ok') else 'BLOCKED'}",
        f"Synced：{payload.get('synced')}",
        f"工作区：{'clean' if payload.get('status_clean') else 'dirty'}",
        "",
    ]
    lines.extend(format_issues(payload.get("blockers") or [], payload.get("warnings") or []))
    return "\n".join(lines) + "\n"


def output_payload(payload: dict[str, object], fmt: str, formatter) -> None:
    if fmt == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(formatter(payload), end="")


def main() -> int:
    args = parse_args()
    summary = collect_summary(Path(args.repo))
    if not summary.get("ok"):
        output_payload(summary, args.format, format_markdown)
        return 1

    if args.mode == "preflight":
        payload = build_preflight(summary)
        output_payload(payload, args.format, format_preflight)
        return 0 if payload.get("ok") else 1
    elif args.mode == "stage-plan":
        payload = build_stage_plan(summary)
        output_payload(payload, args.format, format_stage_plan)
        return 0 if payload.get("ok") else 1
    elif args.mode == "commit-plan":
        payload = build_commit_plan(summary)
        output_payload(payload, args.format, format_commit_plan)
        return 0 if payload.get("ok") else 1
    elif args.mode == "post-push-check":
        payload = build_post_push_check(
            summary,
            expected_branch=args.expected_branch,
            expected_commit=args.expected_commit,
        )
        output_payload(payload, args.format, format_post_push_check)
        return 0 if payload.get("ok") else 1
    elif args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(summary), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
