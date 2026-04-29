#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path, PureWindowsPath


MONOREPO_ROOT_DIRS = {
    "apps",
    "packages",
    "services",
    "libs",
    "modules",
    "projects",
    "skills",
    "crates",
}

HIGH_RISK_PATH_CATEGORIES = {
    "harmony-high-risk",
    "java-high-risk",
    "react-high-risk",
}

HARMONY_CONFIG_NAMES = {
    "build-profile.json5",
    "oh-package.json5",
    "module.json5",
    "app.json5",
}

JAVA_DEPENDENCY_NAMES = {
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "gradlew",
    "gradlew.bat",
}

JAVA_HIGH_RISK_SEGMENTS = {
    "api",
    "config",
    "controller",
    "controllers",
    "dto",
    "migration",
    "migrations",
    "schema",
}

JAVA_HIGH_RISK_FILE_SUFFIXES = (
    "controller.java",
    "dto.java",
    "request.java",
    "response.java",
)

HARMONY_UI_STRUCTURE_SEGMENTS = {
    "abilities",
    "entryability",
    "navigation",
    "navigator",
    "page",
    "pages",
    "router",
    "tabs",
}

REACT_SOURCE_EXTENSIONS = {
    ".cjs",
    ".js",
    ".jsx",
    ".mjs",
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

REACT_HIGH_RISK_SEGMENTS = {
    "api",
    "api-client",
    "auth",
    "data",
    "design-system",
    "loaders",
    "routing",
    "routes",
    "schema",
    "schemas",
    "server",
}

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a structured development workflow brief.")
    parser.add_argument("--repo", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--goal", help="Short task goal for the brief.")
    parser.add_argument("--paths", nargs="*", default=[], help="Planned or affected file paths.")
    parser.add_argument("--interface-change", action="store_true", help="Set when interfaces or contracts change.")
    parser.add_argument("--dependency-change", action="store_true", help="Set when dependencies or toolchains change.")
    parser.add_argument("--schema-change", action="store_true", help="Set when schemas or migrations change.")
    parser.add_argument("--security-sensitive", action="store_true", help="Set when auth, permissions, or secrets are involved.")
    parser.add_argument("--performance-sensitive", action="store_true", help="Set when critical-path performance may change.")
    parser.add_argument("--bugfix", action="store_true", help="Set when the work starts from a bug or failing verification.")
    parser.add_argument(
        "--task-intake",
        action="store_true",
        help="Return a high-level task execution package combining project facts and change plan; does not run validation.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format. Defaults to markdown.",
    )
    return parser.parse_args()


def is_windows_absolute_path(raw_path: str) -> bool:
    return PureWindowsPath(raw_path).is_absolute()


def normalize_path_for_output(raw_path: str) -> str:
    return raw_path.replace("\\", "/")


def normalize_relpath(repo: Path, raw_path: str) -> tuple[str, bool]:
    path = Path(raw_path)
    if not path.is_absolute() and is_windows_absolute_path(raw_path):
        return normalize_path_for_output(raw_path), True
    if raw_path.startswith("/") and not raw_path.startswith("//") and not path.is_absolute():
        return normalize_path_for_output(raw_path), True
    canonical_repo = repo.expanduser().resolve()
    if path.is_absolute():
        resolved = path.expanduser().resolve()
        try:
            return normalize_path_for_output(str(resolved.relative_to(canonical_repo))), False
        except ValueError:
            return normalize_path_for_output(raw_path), True

    resolved = (canonical_repo / path).resolve()
    try:
        return normalize_path_for_output(str(resolved.relative_to(canonical_repo))), False
    except ValueError:
        return normalize_path_for_output(str(resolved)), True


def iter_directory_files(repo: Path, directory: Path):
    for path in directory.rglob("*"):
        relative_parts = path.relative_to(repo).parts
        if any(part in IGNORED_DIRS for part in relative_parts):
            continue
        if path.is_file():
            yield normalize_path_for_output(str(path.relative_to(repo)))


def expand_paths_for_analysis(repo: Path, paths: list[str], outside_repo_paths: list[str]) -> list[str]:
    outside = set(outside_repo_paths)
    expanded = []
    seen = set()
    for path_text in paths:
        candidates = [path_text]
        if path_text not in outside:
            path = repo / path_text
            if path.is_dir():
                files = list(iter_directory_files(repo, path))
                if files:
                    candidates = files
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            expanded.append(candidate)
    return expanded


def infer_module_name(path_text: str) -> str:
    path = Path(path_text)
    if path_text.startswith("/") and not path_text.startswith("//") and not path.is_absolute():
        return "(outside repo)"
    if path.is_absolute() or is_windows_absolute_path(path_text):
        return "(outside repo)"
    parts = path.parts
    if len(parts) <= 1:
        return "(repo root)"
    if parts[0] in MONOREPO_ROOT_DIRS and len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


def normalized_path_text(path_text: str) -> str:
    return path_text.replace("\\", "/").lower()


def path_segments(path_text: str) -> set[str]:
    return {segment for segment in normalized_path_text(path_text).split("/") if segment}


def semantic_path_tokens(path_text: str) -> set[str]:
    tokens = set()
    for segment in normalize_path_for_output(path_text).split("/"):
        stem = Path(segment).stem
        separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", stem)
        tokens.update(token.lower() for token in re.split(r"[^A-Za-z0-9]+", separated) if token)
    return tokens


def has_semantic_path_term(path_text: str, terms: set[str]) -> bool:
    return bool(path_segments(path_text) & terms or semantic_path_tokens(path_text) & terms)


def categorize_path(path_text: str) -> str:
    lowered = path_text.lower()
    name = Path(path_text).name.lower()
    if (
        lowered.startswith("tests/")
        or "/tests/" in lowered
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".spec." in lowered
        or ".test." in lowered
    ):
        return "tests"
    if any(keyword in lowered for keyword in ["migration", "/db/migrate/", "/alembic/"]) or lowered.endswith(".sql"):
        return "schema"
    if name in {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "bun.lockb",
        "pyproject.toml",
        "poetry.lock",
        "uv.lock",
        "requirements.txt",
        "go.mod",
        "cargo.toml",
        "cargo.lock",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle",
        "settings.gradle.kts",
        "gradlew",
        "gradlew.bat",
        "oh-package.json5",
    }:
        return "dependencies"
    if (
        lowered.endswith((".yaml", ".yml", ".toml", ".ini", ".cfg", ".json5"))
        or name in {"makefile", "dockerfile", ".env", ".env.example"}
        or "/config/" in lowered
        or lowered.startswith(".github/workflows/")
    ):
        return "config"
    if lowered.endswith((".md", ".rst", ".txt")) or lowered.startswith("docs/") or "/docs/" in lowered:
        return "docs"
    if Path(path_text).suffix.lower() in {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".ets",
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


def is_harmony_high_risk_path(path_text: str) -> bool:
    lowered = normalized_path_text(path_text)
    name = Path(lowered).name
    if name in HARMONY_CONFIG_NAMES or name.startswith("hvigorfile."):
        return True
    if lowered.startswith("appscope/") and name == "app.json5":
        return True
    if "/resources/" in f"/{lowered}/":
        return True
    if lowered.endswith(".ets"):
        return bool(path_segments(path_text) & HARMONY_UI_STRUCTURE_SEGMENTS)
    return False


def is_harmony_path(path_text: str) -> bool:
    lowered = normalized_path_text(path_text)
    name = Path(lowered).name
    return (
        lowered.endswith(".ets")
        or name in HARMONY_CONFIG_NAMES
        or name.startswith("hvigorfile.")
        or lowered.startswith("entry/")
        or lowered.startswith("feature/")
        or lowered.startswith("appscope/")
    )


def is_java_high_risk_path(path_text: str) -> bool:
    lowered = normalized_path_text(path_text)
    name = Path(lowered).name
    segments = path_segments(path_text)
    if name in JAVA_DEPENDENCY_NAMES:
        return True
    if name.startswith("application.") or name.startswith("bootstrap."):
        return True
    if lowered.endswith(".sql") or "migration" in lowered or "/db/migrate/" in f"/{lowered}":
        return True
    java_like_source = lowered.endswith((".java", ".kt")) or "/src/main/java/" in f"/{lowered}" or "/src/test/java/" in f"/{lowered}"
    if java_like_source and (segments & JAVA_HIGH_RISK_SEGMENTS or name.endswith(JAVA_HIGH_RISK_FILE_SUFFIXES)):
        return True
    return False


def is_java_path(path_text: str) -> bool:
    lowered = normalized_path_text(path_text)
    name = Path(lowered).name
    return (
        lowered.endswith((".java", ".kt"))
        or name in JAVA_DEPENDENCY_NAMES
        or name.startswith("application.")
        or name.startswith("bootstrap.")
        or "/src/main/java/" in f"/{lowered}"
        or "/src/test/java/" in f"/{lowered}"
    )


def is_react_source_path(path_text: str) -> bool:
    lowered = normalized_path_text(path_text)
    return Path(lowered).suffix in REACT_SOURCE_EXTENSIONS


def has_react_stack_context(path_text: str) -> bool:
    lowered = normalized_path_text(path_text)
    name = Path(lowered).name
    segments = path_segments(path_text)
    return (
        lowered.endswith((".tsx", ".jsx"))
        or lowered.startswith(".storybook/")
        or bool(segments & REACT_STACK_CONTEXT_SEGMENTS)
        or any(name.startswith(prefix) for prefix in ["next.config.", "vite.config.", "remix.config."])
    )


def is_react_high_risk_path(path_text: str) -> bool:
    lowered = normalized_path_text(path_text)
    name = Path(lowered).name
    segments = path_segments(path_text)
    if any(name.startswith(prefix) for prefix in ["next.config.", "vite.config.", "remix.config."]):
        return True
    if not is_react_source_path(path_text) or not has_react_stack_context(path_text):
        return False
    if segments & REACT_HIGH_RISK_SEGMENTS:
        return True
    if has_semantic_path_term(path_text, {"auth"}):
        return True
    if any(marker in f"/{lowered}" for marker in ["/app/", "/pages/", "/router", "/ssr"]):
        return True
    return False


def is_react_path(path_text: str) -> bool:
    lowered = normalized_path_text(path_text)
    name = Path(lowered).name
    return (
        (is_react_source_path(path_text) and has_react_stack_context(path_text))
        or any(name.startswith(prefix) for prefix in ["next.config.", "vite.config.", "remix.config."])
        or lowered.startswith(".storybook/")
    )


def classify_path(path_text: str) -> set[str]:
    categories = {categorize_path(path_text)}
    if is_harmony_high_risk_path(path_text):
        categories.add("harmony-high-risk")
    elif is_harmony_path(path_text):
        categories.add("harmony")
    if is_java_high_risk_path(path_text):
        categories.add("java-high-risk")
    elif is_java_path(path_text):
        categories.add("java")
    if is_react_high_risk_path(path_text):
        categories.add("react-high-risk")
    elif is_react_path(path_text):
        categories.add("react-web")
    return categories


def infer_modules(paths: list[str]) -> list[str]:
    modules = []
    seen = set()
    for path_text in paths:
        module_name = infer_module_name(path_text)
        if module_name in seen:
            continue
        seen.add(module_name)
        modules.append(module_name)
    return modules


def needs_full_workflow(
    path_categories: set[str],
    modules: list[str],
    args: argparse.Namespace,
    path_count: int,
    outside_repo_paths: list[str],
) -> bool:
    return bool(
        args.interface_change
        or args.dependency_change
        or args.schema_change
        or args.security_sensitive
        or args.performance_sensitive
        or path_count > 3
        or len(modules) > 1
        or bool(outside_repo_paths)
        or {"dependencies", "config", "schema"} & path_categories
        or HIGH_RISK_PATH_CATEGORIES & path_categories
    )


def validation_expectations(path_categories: set[str], args: argparse.Namespace, outside_repo_paths: list[str]) -> list[str]:
    expectations = []
    if args.bugfix:
        expectations.append("先复现原始失败，再验证修复后的最小闭环命令。")
    if "source" in path_categories or "tests" in path_categories:
        expectations.append("执行受影响范围内的单元测试或最小功能验证。")
    if "dependencies" in path_categories or args.dependency_change:
        expectations.append("补跑构建或安装相关验证，确认依赖和锁文件与环境一致。")
    if "config" in path_categories:
        expectations.append("验证默认值、环境变量和配置加载顺序，不接受静默回退。")
    if "schema" in path_categories or args.schema_change:
        expectations.append("确认迁移/模式变更的前向兼容、回滚路径和历史数据边界。")
    if "harmony-high-risk" in path_categories:
        expectations.append("Harmony 高风险改动先做源码级最小路径检查；命中页面结构、resources、module.json5 或 Hvigor/oh-package/build-profile 时，倾向补一次模块级 hvigor 编译验证。")
    elif "harmony" in path_categories:
        expectations.append("Harmony 小范围改动优先做源码级或手工最小路径验证，不默认升级到 hvigor 编译。")
    if "java-high-risk" in path_categories:
        expectations.append("Java 高风险改动优先执行受影响模块的 ./gradlew test 或 mvn test；controller/API/DTO/migration/config 变更需覆盖契约和数据边界。")
    elif "java" in path_categories:
        expectations.append("Java 源码改动优先执行受影响模块的 ./gradlew test 或 mvn test。")
    if "react-high-risk" in path_categories:
        expectations.append("React Web 高风险改动优先运行相关 package scripts 的 test、lint、typecheck；路由、SSR/data loading、schema、design-system、package/lockfile 变更按风险补 build。")
    elif "react-web" in path_categories:
        expectations.append("React Web 改动优先运行相关 package scripts 的 test、lint 或 typecheck，必要时补 build。")
    if args.performance_sensitive:
        expectations.append("补充关键路径性能或资源使用对比，避免只看功能是否可运行。")
    if args.security_sensitive:
        expectations.append("补看输入校验、权限边界和敏感信息处理。")
    if outside_repo_paths:
        expectations.append("确认仓库边界和仓库外路径是否属于本次交付范围，避免把外部依赖当成仓库内改动。")
    if not expectations:
        expectations.append("至少执行一次能覆盖本次改动主路径的最小充分验证。")
    return expectations


def review_focus(path_categories: set[str], args: argparse.Namespace, outside_repo_paths: list[str]) -> list[str]:
    items = []
    if args.interface_change or "schema" in path_categories:
        items.append("确认接口、配置、数据结构和调用方契约是否同步。")
    if args.dependency_change or "dependencies" in path_categories:
        items.append("检查依赖升级或工具链变化是否带来行为漂移。")
    if args.security_sensitive:
        items.append("重点复查权限、凭据、输入校验和失败路径。")
    if args.performance_sensitive:
        items.append("重点复查关键路径复杂度、IO 和缓存策略。")
    if args.bugfix:
        items.append("确认修复的是根因而不是表象，并验证失败路径。")
    if "config" in path_categories:
        items.append("检查配置默认值、环境差异和旧环境兼容性。")
    if "harmony-high-risk" in path_categories:
        items.append("复查 ArkTS 页面结构、资源引用、module.json5 与构建配置是否同步。")
    if "java-high-risk" in path_categories:
        items.append("复查 Java controller/API/DTO/config/migration 的契约漂移和兼容性。")
    if "react-high-risk" in path_categories:
        items.append("复查 React routing、SSR/data loading、API client/auth/schema/design-system 与 package 变更的回归面。")
    if outside_repo_paths:
        items.append("复查仓库外路径是否只是引用信息，还是意味着任务边界需要重新定义。")
    if not items:
        items.append("独立复查边界条件、异常处理和测试缺口。")
    return items


def recommended_skill_chain(
    path_categories: set[str],
    modules: list[str],
    args: argparse.Namespace,
    full_mode: bool,
    outside_repo_paths: list[str],
) -> list[str]:
    chain = []
    if not args.paths or len(modules) > 1 or full_mode or outside_repo_paths:
        chain.append("project-onboarding")
    if args.bugfix:
        chain.append("verification-and-debug")
    if full_mode or args.interface_change or args.dependency_change or args.schema_change:
        chain.append("code-review-checklist")
    return chain


def build_plan(repo: Path, args: argparse.Namespace) -> dict:
    repo = repo.expanduser().resolve()
    normalized_paths = [normalize_relpath(repo, raw_path) for raw_path in args.paths]
    paths = [item[0] for item in normalized_paths]
    outside_repo_paths = [path_text for path_text, outside_repo in normalized_paths if outside_repo]
    analysis_paths = expand_paths_for_analysis(repo, paths, outside_repo_paths)
    path_categories = set()
    for path_text in analysis_paths:
        path_categories.update(classify_path(path_text))
    modules = infer_modules(analysis_paths)
    full_mode = needs_full_workflow(path_categories, modules, args, len(analysis_paths), outside_repo_paths)
    stages = ["research"]
    if full_mode:
        stages.append("design")
    stages.extend(["implement", "review", "verify"])

    return {
        "repo_path": str(repo.resolve()),
        "goal": args.goal,
        "mode": "full" if full_mode else "light",
        "paths": paths,
        "outside_repo_paths": outside_repo_paths,
        "path_categories": sorted(path_categories),
        "modules": modules,
        "stages": stages,
        "recommended_skill_chain": recommended_skill_chain(path_categories, modules, args, full_mode, outside_repo_paths),
        "validation_expectations": validation_expectations(path_categories, args, outside_repo_paths),
        "review_focus": review_focus(path_categories, args, outside_repo_paths),
    }


def dedupe(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def load_project_facts_module():
    script_path = Path(__file__).resolve().parents[2] / "project-onboarding" / "scripts" / "project_facts.py"
    if not script_path.exists():
        return None, f"未找到 project_facts 辅助脚本：{script_path}"

    spec = importlib.util.spec_from_file_location("structured_dev_project_facts", script_path)
    if spec is None or spec.loader is None:
        return None, f"无法加载 project_facts 辅助脚本：{script_path}"

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:  # pragma: no cover - defensive envelope for broken sibling helper
        return None, f"project_facts 辅助脚本加载失败：{error}"
    return module, None


def collect_project_facts(repo: Path) -> tuple[dict | None, str | None]:
    project_facts, load_error = load_project_facts_module()
    if load_error:
        return None, load_error
    try:
        return project_facts.collect_facts(repo), None
    except Exception as error:  # pragma: no cover - defensive envelope for unexpected scan failures
        return None, f"project_facts 扫描失败：{error}"


def collect_validation_candidates(plan: dict, facts: dict | None) -> dict:
    commands = []
    seen_commands = set()

    def add_command(command: str, reason: str, source: str, scope: str) -> None:
        if command in seen_commands:
            return
        seen_commands.add(command)
        commands.append(
            {
                "command": command,
                "reason": reason,
                "source": source,
                "scope": scope,
            }
        )

    if facts:
        inferred = facts.get("inferred", {})
        for item in inferred.get("validation_commands", []):
            add_command(item["command"], item["reason"], "project_facts.root", ".")
        for module in inferred.get("modules", []):
            module_path = module.get("path", ".")
            for item in module.get("validation_commands", []):
                add_command(item["command"], item["reason"], "project_facts.module", module_path)

    return {
        "commands": commands,
        "expectations": plan["validation_expectations"],
        "not_executed": True,
    }


def task_risks(plan: dict, facts: dict | None, facts_error: str | None) -> list[str]:
    risks = []
    categories = set(plan["path_categories"])
    if facts_error:
        risks.append(f"项目事实扫描失败，执行前需手工补齐事实：{facts_error}")
    if plan["outside_repo_paths"]:
        risks.append("涉及仓库外路径，执行前需确认这些路径是否属于本次交付边界。")
    if plan["mode"] == "full":
        risks.append("已触发 full 工作流，说明变更范围、风险标记或模块数量需要更完整的设计、复查和验证。")
    if {"dependencies", "config", "schema"} & categories:
        risks.append("路径分类包含依赖、配置或模式变更，需关注工具链、默认值、兼容性和回滚边界。")
    if HIGH_RISK_PATH_CATEGORIES & categories:
        risks.append("命中高风险路径分类，需针对对应技术栈补充契约、资源接线或构建链路复查。")
    if facts:
        if facts.get("parse_errors"):
            risks.append("项目配置存在解析异常，不能只依赖自动扫描结论。")
        stacks = facts.get("inferred", {}).get("primary_stacks", [])
        if len(stacks) > 1:
            risks.append("仓库包含多种技术栈，执行前需确认本次任务实际落点和验证范围。")
    return dedupe(risks)


def task_needs_confirmation(plan: dict, facts: dict | None, facts_error: str | None) -> list[str]:
    needs = []
    if not plan["goal"]:
        needs.append("任务目标未提供，需要在执行前明确预期结果。")
    if not plan["paths"]:
        needs.append("未提供涉及路径，需要先收敛影响面再开始实现。")
    if plan["outside_repo_paths"]:
        needs.append("仓库外路径是否纳入本次任务范围。")
    if facts_error:
        needs.append("项目事实扫描失败后的人工补充事实来源。")
    if facts:
        needs.extend(facts.get("needs_confirmation", []))
    return dedupe(needs)


def build_task_intake(repo: Path, args: argparse.Namespace) -> dict:
    repo = repo.expanduser().resolve()
    plan = build_plan(repo, args)
    facts, facts_error = collect_project_facts(repo)
    return {
        "package_type": "task-intake",
        "repo_path": str(repo),
        "goal": args.goal,
        "not_executed": ["implementation", "validation"],
        "plan": plan,
        "facts": facts,
        "facts_error": facts_error,
        "validation_candidates": collect_validation_candidates(plan, facts),
        "risks": task_risks(plan, facts, facts_error),
        "needs_confirmation": task_needs_confirmation(plan, facts, facts_error),
    }


def render_markdown(plan: dict) -> str:
    lines = [
        f"仓库路径：{plan['repo_path']}",
        f"任务目标：{plan['goal'] or '未提供'}",
        f"工作流模式：{plan['mode']}",
        f"涉及路径：{', '.join(plan['paths']) or '未提供'}",
        f"仓库外路径：{', '.join(plan['outside_repo_paths']) or '无'}",
        f"涉及模块：{', '.join(plan['modules']) or '未识别'}",
        f"阶段：{' -> '.join(plan['stages'])}",
        f"建议串联 Skill：{', '.join(plan['recommended_skill_chain']) or '无额外串联'}",
        "验证要求：",
    ]
    for item in plan["validation_expectations"]:
        lines.append(f"- {item}")
    lines.append("复查重点：")
    for item in plan["review_focus"]:
        lines.append(f"- {item}")
    return "\n".join(lines)


def render_task_intake_markdown(package: dict) -> str:
    plan = package["plan"]
    facts = package["facts"]
    lines = [
        f"仓库路径：{package['repo_path']}",
        f"任务目标：{package['goal'] or '未提供'}",
        "执行包类型：task-intake",
        "执行状态：仅生成计划与候选验证，不执行实现或验证命令。",
        "计划摘要：",
        f"- 工作流模式：{plan['mode']}",
        f"- 涉及路径：{', '.join(plan['paths']) or '未提供'}",
        f"- 涉及模块：{', '.join(plan['modules']) or '未识别'}",
        f"- 阶段：{' -> '.join(plan['stages'])}",
        f"- 建议串联 Skill：{', '.join(plan['recommended_skill_chain']) or '无额外串联'}",
        "项目事实：",
    ]
    if facts:
        confirmed = facts["confirmed_facts"]
        inferred = facts["inferred"]
        module_paths = [module["path"] for module in inferred.get("modules", [])]
        lines.extend(
            [
                f"- 项目摘要：{facts['summary'] or '未从入口文档提取到摘要'}",
                f"- 文档入口：{', '.join(confirmed['docs']) or '未发现'}",
                f"- 主技术栈：{', '.join(inferred['primary_stacks']) or '未识别'}",
                f"- 入口候选：{', '.join(inferred['entry_points']) or '未识别'}",
                f"- 模块候选：{', '.join(module_paths) or '未识别'}",
            ]
        )
    else:
        lines.append(f"- 未能扫描项目事实：{package['facts_error']}")

    lines.append("验证候选命令（未执行）：")
    commands = package["validation_candidates"]["commands"]
    if commands:
        for item in commands:
            lines.append(f"- {item['command']}  # scope={item['scope']}; {item['reason']}")
    else:
        lines.append("- 未识别")
    lines.append("验证要求：")
    for item in package["validation_candidates"]["expectations"]:
        lines.append(f"- {item}")
    lines.append("风险：")
    if package["risks"]:
        for item in package["risks"]:
            lines.append(f"- {item}")
    else:
        lines.append("- 当前未识别到额外风险。")
    lines.append("待确认：")
    if package["needs_confirmation"]:
        for item in package["needs_confirmation"]:
            lines.append(f"- {item}")
    else:
        lines.append("- 当前未识别到必须补问的阻塞项。")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    if not repo.exists():
        raise SystemExit(f"Repository path does not exist: {repo}")

    if args.task_intake:
        package = build_task_intake(repo, args)
        if args.format == "json":
            print(json.dumps(package, ensure_ascii=False, indent=2))
        else:
            print(render_task_intake_markdown(package))
        return 1 if package["facts_error"] else 0

    plan = build_plan(repo, args)
    if args.format == "json":
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
