#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PureWindowsPath


GIT_TIMEOUT_SECONDS = 15

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
    "settings.gradle",
    "settings.gradle.kts",
    "gradle.properties",
    "gradle.lockfile",
    "mvnw",
    "mvnw.cmd",
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

HARMONY_TOOLCHAIN_FILES = {
    "build-profile.json5",
    "oh-package.json5",
}

HARMONY_MODULE_FILES = {
    "module.json5",
}

HARMONY_RESOURCE_SEGMENTS = {
    "base",
    "element",
    "media",
    "profile",
    "rawfile",
    "resources",
}

HARMONY_UI_SEGMENTS = {
    "abilities",
    "entryability",
    "navigation",
    "navigator",
    "page",
    "pages",
    "router",
    "tabs",
}

JAVA_PUBLIC_CONTRACT_SEGMENTS = {
    "api",
    "controller",
    "controllers",
    "dto",
    "schema",
    "schemas",
}

JAVA_CONFIG_SEGMENTS = {
    "config",
    "configuration",
    "resources",
}

REACT_ROUTE_SEGMENTS = {
    "app",
    "pages",
    "routes",
    "router",
    "routing",
}

REACT_UI_SEGMENTS = {
    "components",
    "component",
    "hooks",
    "hook",
    "design-system",
    "design_system",
    "ui",
    "styles",
}

REACT_CLIENT_CONTRACT_SEGMENTS = {
    "api",
    "auth",
    "oauth",
    "session",
    "sessions",
    "services",
    "service",
    "schema",
    "schemas",
}

REACT_SOURCE_EXTENSIONS = {
    ".css",
    ".js",
    ".jsx",
    ".less",
    ".mjs",
    ".sass",
    ".scss",
    ".ts",
    ".tsx",
}

REACT_STACK_CONTEXT_SEGMENTS = {
    "frontend",
    "next",
    "react",
    "remix",
    "storybook",
    "web",
}

SPRING_PROFILE_FILE_PREFIXES = (
    "application-",
    "bootstrap-",
)

DEPENDENCY_FILE_NAMES = {name.lower() for name in DEPENDENCY_FILES}
CONFIG_FILE_NAMES = {name.lower() for name in CONFIG_FILES}

PUBLIC_CONTRACT_TERMS = {
    "api",
    "schema",
    "proto",
    "graphql",
    "openapi",
    "dto",
    "contract",
}

SECURITY_SENSITIVE_TERMS = {
    "auth",
    "oauth",
    "permission",
    "permissions",
    "credential",
    "credentials",
    "secret",
    "secrets",
    "token",
    "tokens",
    "crypto",
    "session",
    "sessions",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize review scope and likely risk areas.")
    parser.add_argument("--repo", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--base", help="Git base revision. Defaults to current working tree against HEAD.")
    parser.add_argument("--head", help="Git head revision. Defaults to HEAD when --base is used.")
    parser.add_argument("--files", nargs="*", help="Explicit file list for non-git mode.")
    parser.add_argument(
        "--context",
        action="store_true",
        help="Return a review-context package; does not infer or fabricate findings.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format. Defaults to markdown.",
    )
    return parser.parse_args()


def stringify_process_output(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class GitCommandError(RuntimeError):
    def __init__(
        self,
        *,
        kind: str,
        command: list[str],
        cwd: Path,
        returncode: int | None = None,
        stdout=None,
        stderr=None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.kind = kind
        self.command = command
        self.cwd = cwd
        self.returncode = returncode
        self.stdout = stringify_process_output(stdout)
        self.stderr = stringify_process_output(stderr)
        self.timeout_seconds = timeout_seconds
        super().__init__(self.message)

    @property
    def message(self) -> str:
        command_text = " ".join(self.command)
        if self.kind == "timeout":
            return f"git 命令在 {self.timeout_seconds}s 后超时：{command_text}"
        return f"git 命令退出码为 {self.returncode}：{command_text}"

    def to_dict(self) -> dict:
        return {
            "type": "git_command_error",
            "kind": self.kind,
            "command": self.command,
            "cwd": str(self.cwd),
            "returncode": self.returncode,
            "timeout_seconds": self.timeout_seconds,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "message": self.message,
        }


def run_git_process(repo: Path, args: tuple[str, ...], *, check: bool, binary: bool) -> subprocess.CompletedProcess:
    command = ["git", *args]
    kwargs = {
        "cwd": repo,
        "check": False,
        "capture_output": True,
        "timeout": GIT_TIMEOUT_SECONDS,
    }
    if not binary:
        kwargs.update({"text": True, "encoding": "utf-8", "errors": "replace"})
    try:
        result = subprocess.run(command, **kwargs)
    except subprocess.TimeoutExpired as error:
        raise GitCommandError(
            kind="timeout",
            command=command,
            cwd=repo,
            stdout=error.output,
            stderr=error.stderr,
            timeout_seconds=GIT_TIMEOUT_SECONDS,
        ) from error

    if check and result.returncode != 0:
        raise GitCommandError(
            kind="nonzero_exit",
            command=command,
            cwd=repo,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            timeout_seconds=GIT_TIMEOUT_SECONDS,
        )
    return result


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run_git_process(repo, args, check=check, binary=False)


def git_bytes(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run_git_process(repo, args, check=check, binary=True)


def git_root(repo: Path) -> Path | None:
    result = git_bytes(repo, "rev-parse", "--show-toplevel", check=False)
    if result.returncode != 0:
        return None
    return Path(decode_git_path(result.stdout.rstrip(b"\n")))


def has_head(repo: Path) -> bool:
    return git(repo, "rev-parse", "--verify", "HEAD", check=False).returncode == 0


def normalize_relpath(repo: Path, raw_path: str) -> str:
    path = Path(raw_path)
    if not path.is_absolute() and is_windows_absolute_path(raw_path):
        return normalize_path_for_output(raw_path)
    if path.is_absolute():
        resolved = path.resolve()
        try:
            return normalize_path_for_output(str(resolved.relative_to(repo)))
        except ValueError:
            return normalize_path_for_output(str(resolved))
    return normalize_path_for_output(str(path))


def is_windows_absolute_path(raw_path: str) -> bool:
    return PureWindowsPath(raw_path).is_absolute()


def normalize_path_for_output(raw_path: str) -> str:
    return raw_path.replace("\\", "/")


def resolve_explicit_file(repo: Path, raw_path: str) -> tuple[str, Path | None, bool]:
    if is_windows_absolute_path(raw_path):
        return normalize_path_for_output(raw_path), None, True

    canonical_repo = repo.expanduser().resolve()
    path = Path(raw_path)
    if path.is_absolute():
        resolved = path.expanduser().resolve()
        outside_output = raw_path
    else:
        resolved = (canonical_repo / path).resolve()
        outside_output = raw_path

    try:
        return normalize_path_for_output(str(resolved.relative_to(canonical_repo))), resolved, False
    except ValueError:
        return normalize_path_for_output(outside_output), None, True


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
        relpath, path, outside_repo = resolve_explicit_file(repo, raw_path)
        path_exists = path is not None and path.exists()
        changes.append(
            {
                "path": relpath,
                "status": "outside_repo" if outside_repo else "M" if path_exists else "missing",
                "additions": existing_line_count(path) if path_exists and not outside_repo else 0,
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


def path_segments(path_text: str) -> list[str]:
    return [segment for segment in normalize_path_for_output(path_text).lower().split("/") if segment]


def has_segment(path_text: str, names: set[str]) -> bool:
    return any(segment in names for segment in path_segments(path_text))


def path_name(path_text: str) -> str:
    return normalize_path_for_output(path_text).rsplit("/", 1)[-1].lower()


def path_suffix(path_text: str) -> str:
    return Path(path_name(path_text)).suffix.lower()


def semantic_path_tokens(path_text: str) -> set[str]:
    tokens = set()
    for segment in normalize_path_for_output(path_text).split("/"):
        stem = Path(segment).stem
        separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", stem)
        tokens.update(token.lower() for token in re.split(r"[^A-Za-z0-9]+", separated) if token)
    return tokens


def has_semantic_path_term(path_text: str, names: set[str]) -> bool:
    return bool(set(path_segments(path_text)) & names or semantic_path_tokens(path_text) & names)


def is_hvigor_file(name: str) -> bool:
    return name.startswith("hvigorfile.")


def is_harmony_resource_path(path_text: str) -> bool:
    segments = path_segments(path_text)
    if "resources" not in segments:
        return False
    resource_index = segments.index("resources")
    nested_segments = set(segments[resource_index + 1 :])
    return path_text.replace("\\", "/").lower().startswith("resources/") or bool(
        nested_segments & HARMONY_RESOURCE_SEGMENTS
    )


def is_harmony_config_path(path_text: str) -> bool:
    name = path_name(path_text)
    return name in HARMONY_MODULE_FILES or name in HARMONY_TOOLCHAIN_FILES or is_hvigor_file(name)


def is_harmony_source_path(path_text: str) -> bool:
    return path_suffix(path_text) == ".ets"


def is_harmony_ui_structure_path(path_text: str) -> bool:
    return is_harmony_source_path(path_text) and has_segment(path_text, HARMONY_UI_SEGMENTS)


def is_java_profile_config(path_text: str) -> bool:
    lowered = path_text.lower()
    name = path_name(path_text)
    return (
        name.startswith(SPRING_PROFILE_FILE_PREFIXES)
        and name.endswith((".properties", ".yaml", ".yml"))
    ) or "spring.profiles" in lowered


def is_java_contract_path(path_text: str) -> bool:
    name = path_name(path_text)
    return (
        path_suffix(path_text) == ".java"
        and (
            has_segment(path_text, JAVA_PUBLIC_CONTRACT_SEGMENTS)
            or name.endswith(("controller.java", "dto.java", "request.java", "response.java"))
        )
    ) or has_segment(path_text, {"openapi", "proto", "graphql"})


def is_react_source_file(path_text: str) -> bool:
    return path_suffix(path_text) in REACT_SOURCE_EXTENSIONS


def has_react_stack_context(path_text: str) -> bool:
    lowered = normalize_path_for_output(path_text).lower()
    name = path_name(path_text)
    return (
        lowered.endswith((".tsx", ".jsx"))
        or lowered.startswith(".storybook/")
        or has_segment(path_text, REACT_STACK_CONTEXT_SEGMENTS)
        or any(name.startswith(prefix) for prefix in ["next.config.", "vite.config.", "remix.config."])
    )


def is_react_route_path(path_text: str) -> bool:
    return is_react_source_file(path_text) and has_react_stack_context(path_text) and has_segment(path_text, REACT_ROUTE_SEGMENTS)


def is_react_ui_path(path_text: str) -> bool:
    return is_react_source_file(path_text) and has_react_stack_context(path_text) and has_segment(path_text, REACT_UI_SEGMENTS)


def is_react_client_contract_path(path_text: str) -> bool:
    return (
        is_react_source_file(path_text)
        and has_react_stack_context(path_text)
        and has_semantic_path_term(path_text, REACT_CLIENT_CONTRACT_SEGMENTS)
    )


def categorize_path(path_text: str) -> str:
    lowered = path_text.lower()
    name = path_name(path_text)
    if is_test_path(path_text):
        return "tests"
    if name == "skill.md":
        return "skill-contract"
    if name in DEPENDENCY_FILE_NAMES:
        return "dependencies"
    if is_harmony_resource_path(path_text):
        return "harmony-resources"
    if is_harmony_config_path(path_text):
        return "harmony-config"
    if is_harmony_source_path(path_text):
        return "harmony-source"
    if is_java_profile_config(path_text):
        return "java-config"
    if is_java_contract_path(path_text):
        return "java-contract"
    if is_react_route_path(path_text):
        return "react-routing"
    if is_react_client_contract_path(path_text):
        return "react-client-contract"
    if is_react_ui_path(path_text):
        return "react-ui"
    if "migration" in lowered or lowered.endswith(".sql") or "/alembic/" in lowered or "/db/migrate/" in lowered:
        return "migrations"
    if lowered.endswith((".md", ".rst", ".txt")) or lowered.startswith("docs/") or "/docs/" in lowered:
        return "docs"
    if lowered.startswith(".github/workflows/") or lowered.startswith(".gitlab/") or "jenkins" in lowered:
        return "ci"
    if name in CONFIG_FILE_NAMES or lowered.endswith((".yaml", ".yml", ".toml", ".ini", ".cfg")) or "/config/" in lowered:
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
        name = path_name(change["path"])
        category = categorize_path(change["path"])
        harmony_ui_structure = is_harmony_ui_structure_path(change["path"])
        if category == "dependencies":
            tags.add("dependencies")
            tags.add("build-toolchain")
        if category in {"react-routing", "react-client-contract", "java-contract"} or harmony_ui_structure:
            tags.add("public-contract")
        if harmony_ui_structure:
            tags.add("harmony-ui-structure")
        if category == "harmony-resources":
            tags.add("resource-wiring")
        if category == "harmony-config":
            tags.add("config-behavior")
            if name in HARMONY_MODULE_FILES:
                tags.add("resource-wiring")
            if name in HARMONY_TOOLCHAIN_FILES or is_hvigor_file(name):
                tags.add("build-toolchain")
        if category == "react-routing":
            tags.add("react-routing")
            tags.add("ui-regression")
        if category == "react-client-contract":
            tags.add("client-contract")
        if category == "react-ui":
            tags.add("ui-regression")
        if category == "java-config":
            tags.add("config-behavior")
        if category == "migrations":
            tags.add("data-migration")
            tags.add("public-contract")
        if category == "config":
            tags.add("config-behavior")
        if category == "ci":
            tags.add("delivery-pipeline")
        if category == "skill-contract":
            tags.add("skill-contract")
            tags.add("config-behavior")
            tags.add("public-contract")
        if has_segment(change["path"], JAVA_PUBLIC_CONTRACT_SEGMENTS):
            tags.add("public-contract")
        if has_segment(change["path"], JAVA_CONFIG_SEGMENTS) or is_java_profile_config(change["path"]):
            tags.add("config-behavior")
        if has_react_stack_context(change["path"]) and has_semantic_path_term(change["path"], REACT_CLIENT_CONTRACT_SEGMENTS):
            tags.add("client-contract")
        if has_react_stack_context(change["path"]) and has_segment(change["path"], REACT_UI_SEGMENTS):
            tags.add("ui-regression")
        if has_semantic_path_term(change["path"], {"auth", "oauth", "session", "sessions"}):
            tags.add("security-sensitive")
        if category != "react-ui" and has_semantic_path_term(change["path"], PUBLIC_CONTRACT_TERMS):
            tags.add("public-contract")
        if has_semantic_path_term(change["path"], SECURITY_SENSITIVE_TERMS):
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
    if "harmony-ui-structure" in risk_tags:
        items.append("Harmony 页面改动需重点检查 ArkUI 根节点、导航栈、@Builder 传参和生命周期状态是否仍符合页面结构约束。")
    if "resource-wiring" in risk_tags:
        items.append("Harmony 资源或 module.json5 改动需核对资源名称、路径、Ability/设备配置和引用方是否同步。")
    if "react-routing" in risk_tags:
        items.append("React 路由改动需检查嵌套路由、加载边界、鉴权跳转和浏览器刷新直达路径。")
    if "client-contract" in risk_tags:
        items.append("前端 API、auth、schema 或 service 改动需核对请求/响应契约、错误处理和调用方兼容性。")
    if "ui-regression" in risk_tags:
        items.append("UI 结构、组件、hooks 或样式变更需补看响应式布局、交互状态和视觉回归风险。")
    if "public-contract" in risk_tags:
        items.append("检查接口、配置、事件或持久化格式是否与现有调用方保持兼容。")
    if "build-toolchain" in risk_tags or "dependencies" in risk_tags:
        items.append("核对依赖、锁文件或构建工具链变化是否会改变运行时行为、构建产物或安全面。")
    if "data-migration" in risk_tags:
        items.append("确认迁移脚本的执行顺序、幂等性、回滚路径和历史数据边界。")
    if "config-behavior" in risk_tags:
        items.append("确认默认值、环境变量或配置层级变化不会导致静默回归。")
    if "security-sensitive" in risk_tags:
        items.append("补看输入校验、权限边界和敏感信息处理。")
    if "delivery-pipeline" in risk_tags:
        items.append("检查 CI/CD 或发布脚本变化是否影响现有交付链路。")
    if "skill-contract" in risk_tags:
        items.append("SKILL.md 改动需核对触发条件、运行约定、对外契约和附件路径是否与实现保持一致。")
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
    risky_categories = {
        "source",
        "dependencies",
        "config",
        "migrations",
        "ci",
        "harmony-source",
        "harmony-resources",
        "harmony-config",
        "java-config",
        "java-contract",
        "react-routing",
        "react-client-contract",
        "react-ui",
        "skill-contract",
    }
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


def review_context_questions(summary: dict) -> list[str]:
    questions = []
    if not summary["changed_files"]:
        questions.append("当前审查范围未识别到变更文件，需要确认 base/head 或 --files 参数是否正确。")
    if summary["test_gap"]:
        questions.append("源码或高风险文件已变更但未触及可保留的测试，需要确认验证覆盖。")
    if "dependencies" in summary["risk_tags"] or "build-toolchain" in summary["risk_tags"]:
        questions.append("依赖或构建工具链变化是否需要补充安装、构建或锁文件一致性验证。")
    if "security-sensitive" in summary["risk_tags"]:
        questions.append("权限、输入校验、凭据或会话处理是否需要安全边界复查。")
    return questions


def build_review_context(summary: dict) -> dict:
    return {
        "package_type": "review-context",
        "repo_path": summary["repo_path"],
        "scope": summary,
        "findings": {
            "generated": False,
            "items": [],
            "note": "review-context 只收敛审查范围；有证据的 findings 必须来自后续阅读 diff 和代码。",
        },
        "review_focus": summary["review_focus"],
        "risk_tags": summary["risk_tags"],
        "test_gap": summary["test_gap"],
        "needs_confirmation": review_context_questions(summary),
        "next_steps": [
            "读取高改动文件和相关调用方上下文。",
            "只在有明确证据时输出 findings。",
            "核对受影响范围内的验证命令，不把候选命令当作已执行结果。",
        ],
    }


def render_review_context_markdown(context: dict) -> str:
    scope = context["scope"]
    lines = [
        f"仓库路径：{context['repo_path']}",
        "执行包类型：review-context",
        f"范围来源：{scope['scope_source']}",
        f"变更文件数：{len(scope['changed_files'])}",
        f"风险标签：{', '.join(context['risk_tags']) or '未识别'}",
        f"测试缺口：{'是' if context['test_gap'] else '否'}",
        "Findings 状态：未生成；该入口只收敛审查上下文，不伪造发现项。",
        "Review 焦点：",
    ]
    for item in context["review_focus"]:
        lines.append(f"- {item}")
    lines.append("高改动文件：")
    if scope["hottest_files"]:
        for item in scope["hottest_files"]:
            lines.append(f"- {item['path']} [{item['status']}] +{item['additions']} -{item['deletions']}")
    else:
        lines.append("- 未识别")
    lines.append("待确认：")
    if context["needs_confirmation"]:
        for item in context["needs_confirmation"]:
            lines.append(f"- {item}")
    else:
        lines.append("- 当前未识别到必须补问的阻塞项。")
    lines.append("下一步：")
    for item in context["next_steps"]:
        lines.append(f"- {item}")
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


def build_error_envelope(repo: Path, error: GitCommandError) -> dict:
    return {
        "ok": False,
        "repo_path": format_path_for_output(str(repo.resolve())),
        "error": error.to_dict(),
    }


def render_error_markdown(envelope: dict) -> str:
    error = envelope["error"]
    lines = [
        f"仓库路径：{envelope['repo_path']}",
        "状态：失败",
        f"错误类型：{error['type']}",
        f"错误原因：{error['message']}",
        f"命令：{' '.join(error['command'])}",
    ]
    if error.get("stderr"):
        lines.append(f"stderr：{error['stderr'].strip()}")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    if not repo.exists():
        raise SystemExit(f"Repository path does not exist: {repo}")

    try:
        detected_git_root = git_root(repo)
        if args.files:
            changes, scope_source = collect_explicit_files(repo, args.files)
        elif detected_git_root is not None:
            repo = detected_git_root
            changes, scope_source = collect_git_changes(repo, args.base, args.head)
        else:
            raise SystemExit("No git repository detected and no --files were provided.")
    except GitCommandError as error:
        envelope = build_error_envelope(repo, error)
        if args.format == "json":
            print(json.dumps(envelope, ensure_ascii=False, indent=2))
        else:
            print(render_error_markdown(envelope), file=sys.stderr)
        return 1

    summary = build_summary(repo, changes, scope_source)
    output_summary = prepare_summary_for_output(summary)
    if args.context:
        context = build_review_context(output_summary)
        if args.format == "json":
            print(json.dumps(context, ensure_ascii=False, indent=2))
        else:
            print(render_review_context_markdown(context))
        return 0

    if args.format == "json":
        print(json.dumps(output_summary, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(output_summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
