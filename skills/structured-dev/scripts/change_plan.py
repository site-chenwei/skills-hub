#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


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
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format. Defaults to markdown.",
    )
    return parser.parse_args()


def normalize_relpath(repo: Path, raw_path: str) -> tuple[str, bool]:
    path = Path(raw_path)
    resolved = path.resolve() if path.is_absolute() else (repo / path).resolve()
    try:
        return str(resolved.relative_to(repo)).replace("\\", "/"), False
    except ValueError:
        return str(resolved).replace("\\", "/"), True


def infer_module_name(path_text: str) -> str:
    path = Path(path_text)
    if path.is_absolute():
        return "(outside repo)"
    parts = path.parts
    if len(parts) <= 1:
        return "(repo root)"
    if parts[0] in MONOREPO_ROOT_DIRS and len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


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
    }:
        return "dependencies"
    if (
        lowered.endswith((".yaml", ".yml", ".toml", ".ini", ".cfg"))
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
    normalized_paths = [normalize_relpath(repo, raw_path) for raw_path in args.paths]
    paths = [item[0] for item in normalized_paths]
    outside_repo_paths = [path_text for path_text, outside_repo in normalized_paths if outside_repo]
    path_categories = {categorize_path(path_text) for path_text in paths} if paths else set()
    modules = infer_modules(paths)
    full_mode = needs_full_workflow(path_categories, modules, args, len(paths), outside_repo_paths)
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


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    if not repo.exists():
        raise SystemExit(f"Repository path does not exist: {repo}")

    plan = build_plan(repo, args)
    if args.format == "json":
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
