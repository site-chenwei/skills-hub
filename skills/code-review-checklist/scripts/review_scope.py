#!/usr/bin/env python3

import argparse
import json
import os
import subprocess
from pathlib import Path


DEPENDENCY_FILES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "poetry.lock",
    "uv.lock",
    "Pipfile",
    "Pipfile.lock",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
}

CONFIG_FILES = {
    ".env",
    ".env.example",
    ".editorconfig",
    ".prettierrc",
    ".eslintrc",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize review scope and likely risk areas.")
    parser.add_argument("--repo", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--base", help="Git base revision. Defaults to current working tree against HEAD.")
    parser.add_argument("--head", help="Git head revision. Defaults to HEAD when --base is used.")
    parser.add_argument("--files", nargs="*", help="Explicit file list for non-git mode.")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format. Defaults to markdown.",
    )
    return parser.parse_args()


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def git_bytes(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
    )


def git_root(repo: Path) -> Path | None:
    result = git_bytes(repo, "rev-parse", "--show-toplevel", check=False)
    if result.returncode != 0:
        return None
    return Path(decode_git_path(result.stdout.rstrip(b"\n")))


def has_head(repo: Path) -> bool:
    return git(repo, "rev-parse", "--verify", "HEAD", check=False).returncode == 0


def normalize_relpath(repo: Path, raw_path: str) -> str:
    path = Path(raw_path)
    if path.is_absolute():
        return str(path.resolve().relative_to(repo))
    return str(path).replace("\\", "/")


def existing_line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return 0


def decode_git_path(raw_path: bytes) -> str:
    return os.fsdecode(raw_path)


def format_path_for_output(path_text: str) -> str:
    try:
        path_text.encode("utf-8")
        return path_text
    except UnicodeEncodeError:
        return path_text.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="backslashreplace")


def parse_numstat_z(repo: Path, payload: bytes) -> list[dict]:
    entries = []
    fields = payload.split(b"\0")
    index = 0
    while index < len(fields):
        field = fields[index]
        if not field:
            index += 1
            continue
        parts = field.split(b"\t", 2)
        if len(parts) != 3:
            raise ValueError(f"Unexpected git --numstat -z entry: {field!r}")
        added_raw, deleted_raw, path_raw = parts
        additions = 0 if added_raw == b"-" else int(added_raw)
        deletions = 0 if deleted_raw == b"-" else int(deleted_raw)

        if path_raw:
            path_text = decode_git_path(path_raw)
            index += 1
        else:
            if index + 2 >= len(fields):
                raise ValueError("Incomplete rename/copy entry in git --numstat -z output")
            path_text = decode_git_path(fields[index + 2])
            index += 3

        entries.append(
            {
                "path": normalize_relpath(repo, path_text),
                "additions": additions,
                "deletions": deletions,
            }
        )
    return entries


def parse_name_status_z(repo: Path, payload: bytes) -> list[dict]:
    entries = []
    fields = payload.split(b"\0")
    index = 0
    while index < len(fields):
        status_raw = fields[index]
        if not status_raw:
            index += 1
            continue
        status = status_raw.decode("ascii", errors="strict")
        if index + 1 >= len(fields):
            raise ValueError("Incomplete entry in git --name-status -z output")
        path_count = 2 if status.startswith(("R", "C")) else 1
        if index + path_count >= len(fields):
            raise ValueError("Incomplete rename/copy entry in git --name-status -z output")
        path_text = decode_git_path(fields[index + path_count])
        entries.append({"path": normalize_relpath(repo, path_text), "status": status})
        index += 1 + path_count
    return entries


def collect_name_status_entries(repo: Path, *diff_args: str) -> list[dict]:
    command = list(diff_args)
    if command and command[0] == "diff":
        command.insert(1, "-z")
    else:
        command.append("-z")
    payload = git_bytes(repo, *command).stdout
    return parse_name_status_z(repo, payload)


def collect_numstat_entries(repo: Path, *diff_args: str) -> list[dict]:
    command = list(diff_args)
    if command and command[0] == "diff":
        command.insert(1, "-z")
    else:
        command.append("-z")
    payload = git_bytes(repo, *command).stdout
    return parse_numstat_z(repo, payload)


def collect_untracked_paths(repo: Path) -> list[str]:
    payload = git_bytes(repo, "ls-files", "-z", "--others", "--exclude-standard").stdout
    return [decode_git_path(item) for item in payload.split(b"\0") if item]


def collect_git_changes(repo: Path, base: str | None, head: str | None) -> tuple[list[dict], str]:
    if base:
        target = f"{base}..{head or 'HEAD'}"
        name_status_entries = collect_name_status_entries(repo, "diff", "--name-status", "--find-renames", target)
        numstat_entries = collect_numstat_entries(repo, "diff", "--numstat", "--find-renames", target)
        return merge_change_lists(name_status_entries, numstat_entries), f"git diff {target}"

    if has_head(repo):
        name_status_entries = collect_name_status_entries(repo, "diff", "--name-status", "--find-renames", "HEAD")
        numstat_entries = collect_numstat_entries(repo, "diff", "--numstat", "--find-renames", "HEAD")
        changes = merge_change_lists(name_status_entries, numstat_entries)
        tracked_paths = {item["path"] for item in changes}
        for raw_path in collect_untracked_paths(repo):
            relpath = normalize_relpath(repo, raw_path)
            if relpath in tracked_paths:
                continue
            path = repo / relpath
            changes.append(
                {
                    "path": relpath,
                    "status": "A",
                    "additions": existing_line_count(path),
                    "deletions": 0,
                }
        )
        return sorted(changes, key=lambda item: item["path"]), "git diff HEAD + untracked"

    name_status_entries = collect_name_status_entries(repo, "diff", "--cached", "--name-status", "--find-renames", "--root")
    numstat_entries = collect_numstat_entries(repo, "diff", "--cached", "--numstat", "--find-renames", "--root")
    changes = merge_change_lists(name_status_entries, numstat_entries)
    tracked_paths = {item["path"] for item in changes}
    for raw_path in collect_untracked_paths(repo):
        relpath = normalize_relpath(repo, raw_path)
        if relpath in tracked_paths:
            continue
        path = repo / relpath
        changes.append(
            {
                "path": relpath,
                "status": "A",
                "additions": existing_line_count(path),
                "deletions": 0,
            }
        )
    return sorted(changes, key=lambda item: item["path"]), "git diff --cached --root + untracked"


def merge_change_lists(name_status_entries: list[dict], numstat_entries: list[dict]) -> list[dict]:
    changes: dict[str, dict] = {}
    for entry_data in name_status_entries:
        relpath = entry_data["path"]
        changes[relpath] = {
            "path": relpath,
            "status": entry_data["status"],
            "additions": 0,
            "deletions": 0,
        }
    for entry_data in numstat_entries:
        relpath = entry_data["path"]
        entry = changes.setdefault(
            relpath,
            {"path": relpath, "status": "M", "additions": 0, "deletions": 0},
        )
        entry["additions"] = entry_data["additions"]
        entry["deletions"] = entry_data["deletions"]
    return sorted(changes.values(), key=lambda item: item["path"])


def collect_explicit_files(repo: Path, files: list[str]) -> tuple[list[dict], str]:
    changes = []
    for raw_path in files:
        relpath = normalize_relpath(repo, raw_path)
        path = repo / relpath
        changes.append(
            {
                "path": relpath,
                "status": "M" if path.exists() else "missing",
                "additions": existing_line_count(path) if path.exists() else 0,
                "deletions": 0,
            }
        )
    return changes, "explicit file list"


def is_test_path(path_text: str) -> bool:
    lowered = path_text.lower()
    name = Path(path_text).name.lower()
    return (
        "/tests/" in lowered
        or lowered.startswith("tests/")
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".spec." in lowered
        or ".test." in lowered
    )


def categorize_path(path_text: str) -> str:
    lowered = path_text.lower()
    name = Path(path_text).name
    if is_test_path(path_text):
        return "tests"
    if name in DEPENDENCY_FILES:
        return "dependencies"
    if "migration" in lowered or lowered.endswith(".sql") or "/alembic/" in lowered or "/db/migrate/" in lowered:
        return "migrations"
    if lowered.endswith((".md", ".rst", ".txt")) or lowered.startswith("docs/") or "/docs/" in lowered:
        return "docs"
    if lowered.startswith(".github/workflows/") or lowered.startswith(".gitlab/") or "jenkins" in lowered:
        return "ci"
    if name in CONFIG_FILES or lowered.endswith((".yaml", ".yml", ".toml", ".ini", ".cfg")) or "/config/" in lowered:
        return "config"
    if Path(path_text).suffix.lower() in {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".swift",
        ".dart",
        ".rb",
        ".php",
        ".cs",
    }:
        return "source"
    return "other"


def detect_risk_tags(changes: list[dict]) -> list[str]:
    tags = set()
    for change in changes:
        path_text = change["path"].lower()
        category = categorize_path(change["path"])
        if category == "dependencies":
            tags.add("dependencies")
            tags.add("build-toolchain")
        if category == "migrations":
            tags.add("data-migration")
            tags.add("public-contract")
        if category == "config":
            tags.add("config-behavior")
        if category == "ci":
            tags.add("delivery-pipeline")
        if any(keyword in path_text for keyword in ["api", "schema", "proto", "graphql", "openapi", "dto", "contract"]):
            tags.add("public-contract")
        if any(keyword in path_text for keyword in ["auth", "permission", "credential", "secret", "token", "crypto"]):
            tags.add("security-sensitive")
        if any(keyword in path_text for keyword in ["perf", "cache", "query", "batch", "indexer"]):
            tags.add("performance-sensitive")
    return sorted(tags)


def summarize_test_changes(changes: list[dict]) -> dict:
    summary = {
        "touched": 0,
        "non_deleted": 0,
        "deleted": 0,
        "renamed": 0,
    }
    for change in changes:
        if change["category"] != "tests":
            continue
        summary["touched"] += 1
        status = change["status"]
        if status.startswith("D"):
            summary["deleted"] += 1
            continue
        summary["non_deleted"] += 1
        if status.startswith("R"):
            summary["renamed"] += 1
    return summary


def review_focus(risk_tags: list[str], categories: dict[str, int], test_gap: bool, test_changes: dict) -> list[str]:
    items = []
    if test_changes["deleted"]:
        items.append("本次变更删除了测试，需确认是否同步补上等价覆盖，避免把覆盖退化误判成已验证。")
    if "public-contract" in risk_tags:
        items.append("检查接口、配置、事件或持久化格式是否与现有调用方保持兼容。")
    if "dependencies" in risk_tags:
        items.append("核对依赖或锁文件变化是否会改变运行时行为、构建产物或安全面。")
    if "data-migration" in risk_tags:
        items.append("确认迁移脚本的执行顺序、幂等性、回滚路径和历史数据边界。")
    if "config-behavior" in risk_tags:
        items.append("确认默认值、环境变量或配置层级变化不会导致静默回归。")
    if "security-sensitive" in risk_tags:
        items.append("补看输入校验、权限边界和敏感信息处理。")
    if "delivery-pipeline" in risk_tags:
        items.append("检查 CI/CD 或发布脚本变化是否影响现有交付链路。")
    if "performance-sensitive" in risk_tags:
        items.append("确认关键路径不会引入额外 IO、N+1、缓存失效或批处理回归。")
    if categories.get("source") and test_gap:
        items.append("本次改动触及源码但未触及可保留的测试，重点检查遗漏的失败路径和回归覆盖。")
    if not items:
        items.append("优先从功能正确性、边界条件和测试覆盖判断是否存在真实回归风险。")
    return items


def build_summary(repo: Path, changes: list[dict], scope_source: str) -> dict:
    categories: dict[str, int] = {}
    for change in changes:
        category = categorize_path(change["path"])
        change["category"] = category
        categories[category] = categories.get(category, 0) + 1

    risk_tags = detect_risk_tags(changes)
    test_changes = summarize_test_changes(changes)
    risky_categories = {"source", "dependencies", "config", "migrations", "ci"}
    has_risky_change = any(change["category"] in risky_categories for change in changes)
    test_gap = has_risky_change and test_changes["non_deleted"] == 0
    hottest_files = sorted(
        changes,
        key=lambda item: (item["additions"] + item["deletions"], item["path"]),
        reverse=True,
    )[:5]

    return {
        "repo_path": str(repo.resolve()),
        "scope_source": scope_source,
        "changed_files": changes,
        "categories": categories,
        "risk_tags": risk_tags,
        "test_gap": test_gap,
        "test_changes": test_changes,
        "review_focus": review_focus(risk_tags, categories, test_gap, test_changes),
        "hottest_files": [
            {
                "path": item["path"],
                "status": item["status"],
                "additions": item["additions"],
                "deletions": item["deletions"],
            }
            for item in hottest_files
        ],
    }


def render_markdown(summary: dict) -> str:
    lines = [
        f"仓库路径：{summary['repo_path']}",
        f"范围来源：{summary['scope_source']}",
        f"变更文件数：{len(summary['changed_files'])}",
        f"分类统计：{', '.join(f'{name}={count}' for name, count in sorted(summary['categories'].items())) or '无'}",
        f"风险标签：{', '.join(summary['risk_tags']) or '未识别'}",
        f"测试缺口：{'是' if summary['test_gap'] else '否'}",
        (
            "测试变更："
            f"触及 {summary['test_changes']['touched']} 个，"
            f"保留/新增 {summary['test_changes']['non_deleted']} 个，"
            f"删除 {summary['test_changes']['deleted']} 个，"
            f"重命名 {summary['test_changes']['renamed']} 个"
        ),
        "Review 焦点：",
    ]
    for item in summary["review_focus"]:
        lines.append(f"- {item}")
    lines.append("高改动文件：")
    if summary["hottest_files"]:
        for item in summary["hottest_files"]:
            lines.append(
                f"- {item['path']} [{item['status']}] +{item['additions']} -{item['deletions']}"
            )
    else:
        lines.append("- 未识别")
    return "\n".join(lines)


def prepare_summary_for_output(summary: dict) -> dict:
    payload = dict(summary)
    payload["repo_path"] = format_path_for_output(summary["repo_path"])
    payload["changed_files"] = [
        {**item, "path": format_path_for_output(item["path"])}
        for item in summary["changed_files"]
    ]
    payload["hottest_files"] = [
        {**item, "path": format_path_for_output(item["path"])}
        for item in summary["hottest_files"]
    ]
    return payload


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    if not repo.exists():
        raise SystemExit(f"Repository path does not exist: {repo}")

    detected_git_root = git_root(repo)
    if args.files:
        changes, scope_source = collect_explicit_files(repo, args.files)
    elif detected_git_root is not None:
        repo = detected_git_root
        changes, scope_source = collect_git_changes(repo, args.base, args.head)
    else:
        raise SystemExit("No git repository detected and no --files were provided.")

    summary = build_summary(repo, changes, scope_source)
    output_summary = prepare_summary_for_output(summary)
    if args.format == "json":
        print(json.dumps(output_summary, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(output_summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
