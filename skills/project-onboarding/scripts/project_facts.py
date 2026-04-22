#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ should have tomllib
    tomllib = None


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".next",
    ".nuxt",
    ".pytest_cache",
    "__pycache__",
    "target",
    "out",
}

LANGUAGE_NAMES = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TSX",
    ".js": "JavaScript",
    ".jsx": "JSX",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".dart": "Dart",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".m": "Objective-C",
    ".mm": "Objective-C++",
}

ENTRY_PATTERNS = (
    "main.py",
    "app.py",
    "manage.py",
    "main.ts",
    "main.tsx",
    "main.js",
    "main.jsx",
    "server.ts",
    "server.js",
    "src/main.ts",
    "src/main.tsx",
    "src/index.ts",
    "src/index.tsx",
    "src/index.js",
    "src/main.py",
    "cmd/main.go",
)

PYTHON_CMD_PLACEHOLDER = "<python_cmd>"


def is_test_path(path_text: str) -> bool:
    lowered = path_text.lower()
    name = Path(path_text).name.lower()
    return (
        lowered.startswith("tests/")
        or "/tests/" in lowered
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".spec." in lowered
        or ".test." in lowered
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract project facts for onboarding.")
    parser.add_argument("--repo", default=".", help="Repository root to inspect. Defaults to current directory.")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format. Defaults to markdown.",
    )
    return parser.parse_args()


def iter_files(repo: Path):
    for path in repo.rglob("*"):
        relative_parts = path.relative_to(repo).parts
        if any(part in IGNORED_DIRS for part in relative_parts):
            continue
        if path.is_file():
            yield path


def first_existing(repo: Path, candidates: list[str]) -> Path | None:
    for candidate in candidates:
        path = repo / candidate
        if path.exists():
            return path
    return None


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def format_parse_error(path: Path, error: Exception) -> str:
    return f"{path.name} 解析失败：{error}"


def extract_summary(repo: Path) -> str | None:
    doc_candidates = [
        first_existing(repo, ["PROJECT.md"]),
        *sorted(repo.glob("README*")),
    ]
    for doc in [item for item in doc_candidates if item]:
        for raw_line in read_text(doc).splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                heading = line.lstrip("#").strip()
                if heading:
                    return heading
                continue
            return line[:160]
    return None


def detect_package_manager(repo: Path, package_data: dict | None) -> str | None:
    package_manager = package_data.get("packageManager") if isinstance(package_data, dict) else None
    if isinstance(package_manager, str) and package_manager.strip():
        return package_manager.split("@", 1)[0]
    for filename, manager in [
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"),
        ("package-lock.json", "npm"),
    ]:
        if (repo / filename).exists():
            return manager
    if (repo / "package.json").exists():
        return "npm"
    return None


def load_package_json(repo: Path) -> tuple[dict | None, str | None]:
    package_json = repo / "package.json"
    if not package_json.exists():
        return None, None
    try:
        return json.loads(read_text(package_json)), None
    except (json.JSONDecodeError, OSError) as error:
        return None, format_parse_error(package_json, error)


def load_pyproject(repo: Path) -> tuple[dict | None, str | None]:
    pyproject = repo / "pyproject.toml"
    if not pyproject.exists() or tomllib is None:
        return None, None
    try:
        return tomllib.loads(read_text(pyproject)), None
    except (tomllib.TOMLDecodeError, OSError) as error:
        return None, format_parse_error(pyproject, error)


def detect_configs(repo: Path) -> list[str]:
    config_names = [
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "uv.lock",
        "poetry.lock",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "Makefile",
        "docker-compose.yml",
        "docker-compose.yaml",
    ]
    present = []
    for name in config_names:
        if (repo / name).exists():
            present.append(name)
    return present


def detect_languages(repo: Path) -> list[dict]:
    counts: dict[str, int] = {}
    for path in iter_files(repo):
        language = LANGUAGE_NAMES.get(path.suffix.lower())
        if not language:
            continue
        counts[language] = counts.get(language, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"name": name, "files": file_count} for name, file_count in ranked[:6]]


def language_names(languages: list[dict]) -> set[str]:
    return {item["name"] for item in languages}


def detect_top_level_dirs(repo: Path) -> list[str]:
    dirs = []
    for child in sorted(repo.iterdir()):
        if not child.is_dir():
            continue
        if child.name in IGNORED_DIRS or child.name.startswith("."):
            continue
        dirs.append(child.name)
    return dirs


def detect_primary_stacks(
    repo: Path,
    package_data: dict | None,
    pyproject_data: dict | None,
    languages: list[dict],
) -> list[str]:
    stacks = []
    names = language_names(languages)
    if (
        package_data is not None
        or detect_package_manager(repo, package_data) is not None
        or any(name in names for name in {"JavaScript", "JSX", "TypeScript", "TSX"})
    ):
        stacks.append("node")
    if (repo / "tsconfig.json").exists() or any(name in names for name in {"TypeScript", "TSX"}):
        stacks.append("typescript")
    if (
        pyproject_data is not None
        or (repo / "requirements.txt").exists()
        or (repo / "uv.lock").exists()
        or "Python" in names
    ):
        stacks.append("python")
    if (repo / "go.mod").exists() or "Go" in names:
        stacks.append("go")
    if (repo / "Cargo.toml").exists() or "Rust" in names:
        stacks.append("rust")
    if (
        (repo / "pom.xml").exists()
        or (repo / "build.gradle").exists()
        or (repo / "build.gradle.kts").exists()
        or any(name in names for name in {"Java", "Kotlin"})
    ):
        stacks.append("jvm")
    return stacks


def add_candidate(candidates: list[dict], command: str, reason: str) -> None:
    if any(item["command"] == command for item in candidates):
        return
    candidates.append({"command": command, "reason": reason})


def has_python_tests(repo: Path) -> bool:
    for path in iter_files(repo):
        relative = str(path.relative_to(repo)).replace("\\", "/")
        if path.suffix.lower() == ".py" and is_test_path(relative):
            return True
    return False


def detect_validation_commands(
    repo: Path,
    package_data: dict | None,
    pyproject_data: dict | None,
    primary_stacks: list[str],
) -> list[dict]:
    candidates: list[dict] = []
    package_manager = detect_package_manager(repo, package_data)
    scripts = package_data.get("scripts", {}) if isinstance(package_data, dict) else {}
    if package_manager and isinstance(scripts, dict):
        if "test" in scripts:
            add_candidate(candidates, f"{package_manager} test", "package.json scripts.test")
        if "lint" in scripts:
            add_candidate(candidates, f"{package_manager} run lint", "package.json scripts.lint")
        if "build" in scripts:
            add_candidate(candidates, f"{package_manager} run build", "package.json scripts.build")

    if "python" in primary_stacks:
        if has_python_tests(repo):
            add_candidate(candidates, f"{PYTHON_CMD_PLACEHOLDER} -m unittest discover", "Python test files detected")
        if (
            pyproject_data is not None
            or (repo / "requirements.txt").exists()
            or (repo / "pytest.ini").exists()
            or (repo / "tox.ini").exists()
            or (repo / "conftest.py").exists()
        ):
            add_candidate(candidates, f"{PYTHON_CMD_PLACEHOLDER} -m pytest", "Python project config detected")
        if (repo / "uv.lock").exists():
            add_candidate(candidates, "uv run python -m unittest discover", "uv.lock detected")
        if pyproject_data and "tool" in pyproject_data and "ruff" in pyproject_data["tool"]:
            add_candidate(candidates, f"{PYTHON_CMD_PLACEHOLDER} -m ruff check .", "pyproject defines Ruff config")
    if (repo / "go.mod").exists():
        add_candidate(candidates, "go test ./...", "Go module detected")
    if (repo / "Cargo.toml").exists():
        add_candidate(candidates, "cargo test", "Cargo workspace detected")
    if (repo / "pom.xml").exists():
        add_candidate(candidates, "mvn test", "Maven project detected")
    if (repo / "build.gradle").exists() or (repo / "build.gradle.kts").exists():
        add_candidate(candidates, "./gradlew test", "Gradle project detected")
    if (repo / "Makefile").exists():
        add_candidate(candidates, "make test", "Makefile detected")

    return candidates


def detect_entry_points(repo: Path) -> list[str]:
    entries = []
    for candidate in ENTRY_PATTERNS:
        path = repo / candidate
        if path.exists():
            entries.append(candidate)
    return entries[:6]


def collect_facts(repo: Path) -> dict:
    package_data, package_error = load_package_json(repo)
    pyproject_data, pyproject_error = load_pyproject(repo)
    parse_errors = [error for error in [package_error, pyproject_error] if error]
    docs = []
    if (repo / "PROJECT.md").exists():
        docs.append("PROJECT.md")
    docs.extend(sorted(path.name for path in repo.glob("README*")))
    if (repo / "docs").is_dir():
        docs.append("docs/")

    languages = detect_languages(repo)
    package_manager = detect_package_manager(repo, package_data)
    primary_stacks = detect_primary_stacks(repo, package_data, pyproject_data, languages)
    validation_commands = detect_validation_commands(repo, package_data, pyproject_data, primary_stacks)
    entry_points = detect_entry_points(repo)
    top_level_dirs = detect_top_level_dirs(repo)

    needs_confirmation = []
    if parse_errors:
        needs_confirmation.append("关键配置文件存在解析失败，需以源码和其他配置交叉确认项目事实。")
    if not docs:
        needs_confirmation.append("缺少 PROJECT.md / README，项目目标需要从源码和配置交叉确认。")
    if not validation_commands:
        needs_confirmation.append("未识别到明确的最小验证命令，需要手工确认测试或构建入口。")
    if len(primary_stacks) > 1:
        needs_confirmation.append("仓库包含多种技术栈，需要确认本次任务实际落点。")
    if not entry_points:
        needs_confirmation.append("未识别到明显入口文件，需要结合模块目录确认主执行链路。")

    return {
        "repo_path": str(repo.resolve()),
        "summary": extract_summary(repo),
        "parse_errors": parse_errors,
        "confirmed_facts": {
            "docs": docs,
            "configs": detect_configs(repo),
            "package_manager": package_manager,
            "top_level_dirs": top_level_dirs,
        },
        "inferred": {
            "primary_stacks": primary_stacks,
            "languages": languages,
            "validation_commands": validation_commands,
            "entry_points": entry_points,
        },
        "needs_confirmation": needs_confirmation,
    }


def render_markdown(facts: dict) -> str:
    confirmed = facts["confirmed_facts"]
    inferred = facts["inferred"]
    language_summary = ", ".join(f"{item['name']}({item['files']})" for item in inferred["languages"]) or "未识别"
    lines = [
        f"仓库路径：{facts['repo_path']}",
        f"项目摘要：{facts['summary'] or '未从入口文档提取到摘要'}",
        "已确认事实：",
        f"- 文档入口：{', '.join(confirmed['docs']) or '未发现'}",
        f"- 关键配置：{', '.join(confirmed['configs']) or '未发现'}",
        f"- 包管理器：{confirmed['package_manager'] or '未识别'}",
        f"- 顶层目录：{', '.join(confirmed['top_level_dirs']) or '未发现'}",
        "推断：",
        f"- 主技术栈：{', '.join(inferred['primary_stacks']) or '未识别'}",
        f"- 主要语言：{language_summary}",
        f"- 入口候选：{', '.join(inferred['entry_points']) or '未识别'}",
        "- 验证命令候选：",
    ]
    if inferred["validation_commands"]:
        for item in inferred["validation_commands"]:
            lines.append(f"  - {item['command']}  # {item['reason']}")
    else:
        lines.append("  - 未识别")
    if facts["parse_errors"]:
        lines.append("解析异常：")
        for item in facts["parse_errors"]:
            lines.append(f"- {item}")
    lines.append("待确认：")
    if facts["needs_confirmation"]:
        for item in facts["needs_confirmation"]:
            lines.append(f"- {item}")
    else:
        lines.append("- 当前未识别到必须补问的阻塞项。")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    if not repo.exists():
        raise SystemExit(f"Repository path does not exist: {repo}")
    facts = collect_facts(repo)
    if args.format == "json":
        print(json.dumps(facts, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(facts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
