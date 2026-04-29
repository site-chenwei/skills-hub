#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ should have tomllib
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".gradle",
    ".hvigor",
    ".venv",
    "venv",
    "node_modules",
    "oh_modules",
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
    ".ets": "ArkTS",
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
    "entry/src/main/ets/entryability/EntryAbility.ets",
    "entry/src/main/ets/pages/Index.ets",
    "src/App.tsx",
    "src/App.jsx",
    "app/page.tsx",
    "pages/index.tsx",
    "src/main/java",
)

PYTHON_CMD_PLACEHOLDER = "<python_cmd>"

PACKAGE_SCRIPT_ORDER = (
    ("test", "package.json scripts.test"),
    ("lint", "package.json scripts.lint"),
    ("typecheck", "package.json scripts.typecheck"),
    ("build", "package.json scripts.build"),
)

HARMONY_ROOT_CONFIGS = {
    "build-profile.json5",
    "oh-package.json5",
}

HARMONY_VALIDATION_TEMPLATE = "$harmony-build verify --task <public module task>"

JAVA_CONFIG_NAMES = {
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "gradlew",
    "gradlew.bat",
}

SPRING_CONFIG_NAMES = {
    "application.properties",
    "application.yml",
    "application.yaml",
    "bootstrap.properties",
    "bootstrap.yml",
    "bootstrap.yaml",
}

REACT_DEPENDENCY_NAMES = {
    "react",
    "react-dom",
    "next",
    "@remix-run/react",
    "@vitejs/plugin-react",
    "@vitejs/plugin-react-swc",
    "react-scripts",
}

REACT_CONFIG_NAMES = {
    "vite.config.js",
    "vite.config.mjs",
    "vite.config.ts",
    "vite.config.mts",
    "next.config.js",
    "next.config.mjs",
    "next.config.ts",
    "remix.config.js",
    "remix.config.mjs",
    "remix.config.ts",
}

REACT_TEST_OR_STORYBOOK_DEPS = {
    "vitest",
    "jest",
    "@testing-library/react",
    "@playwright/test",
    "cypress",
    "storybook",
    "@storybook/react",
    "@storybook/react-vite",
    "@storybook/nextjs",
}

MODULE_MARKER_NAMES = {
    "package.json",
    "pyproject.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
}

SKILL_MODULE_MARKER_NAMES = {
    "SKILL.md",
    "run.py",
}


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


def relative_path(repo: Path, path: Path) -> str:
    return str(path.relative_to(repo)).replace("\\", "/")


def module_path(repo: Path, path: Path) -> str:
    relative = str(path.relative_to(repo)).replace("\\", "/")
    return relative if relative else "."


def quote_command_path(path_text: str) -> str:
    return shlex.quote(path_text)


def scope_command(command: str, path_text: str) -> str:
    if path_text == ".":
        return command
    return f"cd {quote_command_path(path_text)} && {command}"


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


def strip_toml_comment(line: str) -> str:
    in_string = False
    quote_char = ""
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char in {"'", '"'}:
            if in_string and char == quote_char:
                in_string = False
                quote_char = ""
            elif not in_string:
                in_string = True
                quote_char = char
            continue
        if char == "#" and not in_string:
            return line[:index].strip()
    return line.strip()


def parse_toml_key(key: str) -> list[str]:
    parts = [part.strip().strip('"').strip("'") for part in key.split(".")]
    if not parts or any(not part for part in parts):
        raise ValueError(f"无效键名：{key}")
    return parts


def parse_simple_toml_value(value: str):
    value = value.strip()
    if not value:
        raise ValueError("缺少值")
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith(('"', "'")) != value.endswith(('"', "'")):
        raise ValueError("字符串引号不匹配")
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.startswith("[") != value.endswith("]"):
        raise ValueError("数组括号不匹配")
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [parse_simple_toml_value(item.strip()) for item in split_toml_array_items(inner) if item.strip()]
    if value.startswith("{") != value.endswith("}"):
        raise ValueError("内联表括号不匹配")
    if value.startswith("{") and value.endswith("}"):
        raise ValueError("简化 TOML 解析器不支持内联表")
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"不支持的值：{value}") from error


def split_toml_array_items(inner: str) -> list[str]:
    items = []
    current = []
    in_string = False
    quote_char = ""
    escaped = False
    for char in inner:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and in_string:
            current.append(char)
            escaped = True
            continue
        if char in {"'", '"'}:
            current.append(char)
            if in_string and char == quote_char:
                in_string = False
                quote_char = ""
            elif not in_string:
                in_string = True
                quote_char = char
            continue
        if char == "," and not in_string:
            items.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if in_string:
        raise ValueError("数组字符串引号不匹配")
    tail = "".join(current).strip()
    if tail:
        items.append(tail)
    return items


def is_incomplete_toml_array(value: str) -> bool:
    if not value.lstrip().startswith("["):
        return False
    in_string = False
    quote_char = ""
    escaped = False
    depth = 0
    for char in value:
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char in {"'", '"'}:
            if in_string and char == quote_char:
                in_string = False
                quote_char = ""
            elif not in_string:
                in_string = True
                quote_char = char
            continue
        if in_string:
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
    return depth > 0


def parse_simple_toml(text: str) -> dict:
    data: dict = {}
    current = data
    pending_array: dict | None = None
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = strip_toml_comment(raw_line)
        if pending_array is not None:
            if line:
                pending_array["values"].append(line)
            value = " ".join(pending_array["values"])
            if is_incomplete_toml_array(value):
                continue
            pending_array["target"][pending_array["key"]] = parse_simple_toml_value(value)
            pending_array = None
            continue
        if not line:
            continue
        if line.startswith("["):
            if not line.endswith("]") or line in {"[]", "[[]]"}:
                raise ValueError(f"第 {line_number} 行表头无效")
            section = line.strip("[]").strip()
            current = data
            for part in parse_toml_key(section):
                current = current.setdefault(part, {})
                if not isinstance(current, dict):
                    raise ValueError(f"第 {line_number} 行表头冲突")
            continue
        if "=" not in line:
            raise ValueError(f"第 {line_number} 行缺少 '='")
        key, value = line.split("=", 1)
        target = current
        parts = parse_toml_key(key.strip())
        for part in parts[:-1]:
            target = target.setdefault(part, {})
            if not isinstance(target, dict):
                raise ValueError(f"第 {line_number} 行键名冲突")
        value_text = value.strip()
        if is_incomplete_toml_array(value_text):
            pending_array = {
                "line_number": line_number,
                "target": target,
                "key": parts[-1],
                "values": [value_text],
            }
            continue
        target[parts[-1]] = parse_simple_toml_value(value_text)
    if pending_array is not None:
        raise ValueError(f"第 {pending_array['line_number']} 行数组未闭合")
    return data


def load_pyproject(repo: Path) -> tuple[dict | None, str | None]:
    pyproject = repo / "pyproject.toml"
    if not pyproject.exists():
        return None, None
    try:
        text = read_text(pyproject)
        if tomllib is not None:
            return tomllib.loads(text), None
        return parse_simple_toml(text), None
    except (OSError, ValueError) as error:
        return None, format_parse_error(pyproject, error)


def detect_configs(repo: Path) -> list[str]:
    config_names = [
        "SKILL.md",
        "run.py",
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "uv.lock",
        "poetry.lock",
        "Cargo.toml",
        "go.mod",
        "tsconfig.json",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle",
        "settings.gradle.kts",
        "gradlew",
        "gradlew.bat",
        "build-profile.json5",
        "oh-package.json5",
        "AppScope/app.json5",
        "Makefile",
        "docker-compose.yml",
        "docker-compose.yaml",
    ]
    config_names.extend(sorted(REACT_CONFIG_NAMES))
    present = []
    for name in config_names:
        if (repo / name).exists():
            present.append(name)
    if (repo / ".storybook").is_dir():
        present.append(".storybook/")
    for path in iter_files(repo):
        relative = relative_path(repo, path)
        name = path.name.lower()
        if name == "module.json5" or name.startswith("hvigorfile.") or name in SPRING_CONFIG_NAMES:
            if relative not in present:
                present.append(relative)
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


def package_dependency_names(package_data: dict | None) -> set[str]:
    names: set[str] = set()
    if not isinstance(package_data, dict):
        return names
    for section in ["dependencies", "devDependencies", "peerDependencies", "optionalDependencies"]:
        values = package_data.get(section)
        if isinstance(values, dict):
            names.update(str(name).lower() for name in values)
    return names


def package_script_values(package_data: dict | None) -> list[str]:
    if not isinstance(package_data, dict):
        return []
    scripts = package_data.get("scripts", {})
    if not isinstance(scripts, dict):
        return []
    return [str(value).lower() for value in scripts.values()]


def has_harmony_signals(repo: Path) -> bool:
    for name in HARMONY_ROOT_CONFIGS:
        if (repo / name).exists():
            return True
    if (repo / "AppScope" / "app.json5").exists():
        return True
    for path in iter_files(repo):
        name = path.name.lower()
        if name == "module.json5" or name.startswith("hvigorfile."):
            return True
        if path.suffix.lower() == ".ets":
            return True
    return False


def has_harmony_high_risk_signals(repo: Path) -> bool:
    for name in HARMONY_ROOT_CONFIGS:
        if (repo / name).exists():
            return True
    if (repo / "AppScope" / "app.json5").exists():
        return True
    for path in iter_files(repo):
        relative = relative_path(repo, path).lower()
        name = path.name.lower()
        if name == "module.json5" or name.startswith("hvigorfile."):
            return True
        if path.suffix.lower() == ".ets" and any(
            marker in f"/{relative}" for marker in ["/pages/", "/entry/src/main/ets/", "/feature/"]
        ):
            return True
        if "/resources/" in f"/{relative}/":
            return True
    return False


def has_java_signals(repo: Path, languages: list[dict]) -> bool:
    names = language_names(languages)
    if "Java" in names or "Kotlin" in names:
        return True
    if any((repo / name).exists() for name in JAVA_CONFIG_NAMES):
        return True
    score = 0
    for path in iter_files(repo):
        relative = relative_path(repo, path).lower()
        name = path.name.lower()
        if name in SPRING_CONFIG_NAMES:
            score += 2
        if "/src/main/java/" in f"/{relative}" or "/src/test/java/" in f"/{relative}":
            score += 2
        if any(marker in f"/{relative}" for marker in ["/controller/", "/service/", "/repository/"]):
            score += 1
        if "migration" in relative or "/db/migrate/" in relative or "/db/migration/" in relative:
            score += 1
        if score >= 2:
            return True
    return score >= 2


def has_react_web_signals(repo: Path, package_data: dict | None, languages: list[dict]) -> bool:
    deps = package_dependency_names(package_data)
    scripts = package_script_values(package_data)
    names = language_names(languages)
    has_react_web_dependency = bool(deps & (REACT_DEPENDENCY_NAMES - {"react"}))
    has_react_tooling = bool(deps & REACT_TEST_OR_STORYBOOK_DEPS)
    has_react_framework_script = any(
        marker in script for script in scripts for marker in ["next", "react-scripts", "remix", "storybook"]
    )
    has_vite_script = any("vite" in script for script in scripts)
    has_react_config = any((repo / name).exists() for name in REACT_CONFIG_NAMES) or (repo / ".storybook").is_dir()
    has_react_entry = any(
        (repo / candidate).exists()
        for candidate in [
            "src/App.tsx",
            "src/App.jsx",
            "src/main.tsx",
            "src/index.tsx",
            "app/page.tsx",
            "pages/index.tsx",
        ]
    )
    has_react_dependency = has_react_web_dependency or ("react" in deps and (has_react_entry or has_react_config))
    return bool(
        has_react_dependency
        or (has_react_tooling and any(name in names for name in {"TSX", "JSX"}))
        or (has_react_framework_script and any(name in names for name in {"TSX", "JSX", "TypeScript", "JavaScript"}))
        or (has_vite_script and (has_react_dependency or any(name in names for name in {"TSX", "JSX"})))
        or (has_react_config and (has_react_dependency or any(name in names for name in {"TSX", "JSX"})))
        or has_react_entry
    )


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
    if has_harmony_signals(repo):
        stacks.append("harmony")
    if has_react_web_signals(repo, package_data, languages):
        stacks.append("react-web")
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
    if has_java_signals(repo, languages):
        stacks.append("java")
    return stacks


def add_candidate(candidates: list[dict], command: str, reason: str) -> None:
    if any(item["command"] == command for item in candidates):
        return
    candidates.append({"command": command, "reason": reason})


def package_script_command(package_manager: str, script_name: str) -> str:
    if script_name == "test":
        return f"{package_manager} test"
    return f"{package_manager} run {script_name}"


def has_python_tests(repo: Path) -> bool:
    for path in iter_files(repo):
        relative = str(path.relative_to(repo)).replace("\\", "/")
        if path.suffix.lower() == ".py" and is_test_path(relative):
            return True
    return False


def has_skills_hub_unittest_aggregator(repo: Path) -> bool:
    return (repo / "skills" / "test_all_skills.py").is_file()


def is_skill_module_root(repo: Path) -> bool:
    return (repo / "SKILL.md").is_file() and (repo / "run.py").is_file()


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
        for script_name, reason in PACKAGE_SCRIPT_ORDER:
            if script_name in scripts:
                add_candidate(candidates, package_script_command(package_manager, script_name), reason)

    if "python" in primary_stacks:
        if has_skills_hub_unittest_aggregator(repo):
            add_candidate(
                candidates,
                f"{PYTHON_CMD_PLACEHOLDER} -m unittest skills.test_all_skills",
                "skills/test_all_skills.py aggregate unittest entry detected",
            )
        elif has_python_tests(repo):
            command = f"{PYTHON_CMD_PLACEHOLDER} -m unittest discover"
            if is_skill_module_root(repo) and (repo / "tests").is_dir():
                command = f"{command} -s tests"
            add_candidate(candidates, command, "Python test files detected")
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
    if "harmony" in primary_stacks and has_harmony_high_risk_signals(repo):
        add_candidate(
            candidates,
            HARMONY_VALIDATION_TEMPLATE,
            "Harmony high-risk candidate; confirm the public module task before running verification",
        )
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


def detect_module_roots(repo: Path) -> list[Path]:
    roots: set[Path] = set()
    for path in iter_files(repo):
        if path.name in MODULE_MARKER_NAMES or is_skill_module_marker(repo, path):
            roots.add(path.parent)
    return sorted(roots, key=lambda path: module_path(repo, path))


def is_skill_module_marker(repo: Path, path: Path) -> bool:
    if path.name not in SKILL_MODULE_MARKER_NAMES:
        return False
    if path.name == "SKILL.md":
        return True
    if (path.parent / "SKILL.md").is_file():
        return True
    relative_parts = path.relative_to(repo).parts
    return len(relative_parts) == 3 and relative_parts[0] == "skills"


def localize_module_validation_commands(
    module_root: Path,
    path_text: str,
    validation_commands: list[dict],
) -> list[dict]:
    localized = []
    for item in validation_commands:
        command = item["command"]
        if (
            command == "./gradlew test"
            and path_text != "."
            and not (module_root / "gradlew").exists()
            and not (module_root / "gradlew.bat").exists()
        ):
            command = "gradle test"
        localized.append(
            {
                "command": scope_command(command, path_text),
                "reason": item["reason"],
            }
        )
    return localized


def collect_modules(repo: Path) -> list[dict]:
    modules = []
    for root in detect_module_roots(repo):
        package_data, package_error = load_package_json(root)
        pyproject_data, pyproject_error = load_pyproject(root)
        languages = detect_languages(root)
        stacks = detect_primary_stacks(root, package_data, pyproject_data, languages)
        configs = detect_configs(root)
        if not stacks and not configs:
            continue

        path_text = module_path(repo, root)
        validation_commands = detect_validation_commands(root, package_data, pyproject_data, stacks)
        module = {
            "path": path_text,
            "stacks": stacks,
            "configs": configs,
            "package_manager": detect_package_manager(root, package_data),
            "validation_commands": localize_module_validation_commands(root, path_text, validation_commands),
        }
        parse_errors = [error for error in [package_error, pyproject_error] if error]
        if parse_errors:
            module["parse_errors"] = parse_errors
        modules.append(module)
    return modules


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
    modules = collect_modules(repo)

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
            "modules": modules,
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
    lines.append("- 模块候选：")
    modules = inferred.get("modules", [])
    if modules:
        for module in modules:
            stacks = ", ".join(module["stacks"]) or "未识别"
            configs = ", ".join(module["configs"]) or "未发现"
            package_manager = module["package_manager"] or "未识别"
            lines.append(
                f"  - {module['path']}  # stacks={stacks}; package_manager={package_manager}; configs={configs}"
            )
            for item in module["validation_commands"]:
                lines.append(f"    - {item['command']}  # {item['reason']}")
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
