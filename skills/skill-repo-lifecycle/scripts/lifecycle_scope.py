#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path


EXCLUDE_NAMES = {"__pycache__", ".pytest_cache"}
EXCLUDE_PATTERNS = ("*.pyc",)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize a repo-owned skill lifecycle scope.")
    parser.add_argument("--repo", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--install-root", default="/Users/bill/.cc-switch/skills", help="Local runtime skill install root.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser.parse_args()


def is_excluded(path: Path) -> bool:
    if any(part in EXCLUDE_NAMES for part in path.parts):
        return True
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in EXCLUDE_PATTERNS)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_fingerprint(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if is_excluded(relative):
            continue
        if path.is_file():
            result[str(relative).replace("\\", "/")] = file_digest(path)
    return result


def discover_skill_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir() and (path / "SKILL.md").exists())


def discover_skills(repo: Path) -> list[Path]:
    skills_dir = repo / "skills"
    return discover_skill_dirs(skills_dir)


def discover_archived_skills(repo: Path) -> list[Path]:
    skills_dir = repo / "archive" / "skills"
    return discover_skill_dirs(skills_dir)


def installed_skill_exists(path: Path) -> bool:
    return path.exists() and (path / "SKILL.md").exists()


def collect_active_skill(skill_dir: Path, install_root: Path) -> dict[str, object]:
    install_dir = install_root.expanduser() / skill_dir.name
    source_fp = directory_fingerprint(skill_dir)
    install_fp = directory_fingerprint(install_dir)
    missing = []
    for required in ("SKILL.md", "agents/openai.yaml"):
        if not (skill_dir / required).exists():
            missing.append(required)
    has_run = (skill_dir / "run.py").exists()
    has_tests = (skill_dir / "tests").exists() and any((skill_dir / "tests").glob("test_*.py"))
    return {
        "name": skill_dir.name,
        "source_path": str(skill_dir),
        "has_run_py": has_run,
        "has_tests": has_tests,
        "missing_required": missing,
        "installed": installed_skill_exists(install_dir),
        "install_path": str(install_dir),
        "install_matches_source": bool(install_fp) and source_fp == install_fp,
    }


def collect_archived_skill(skill_dir: Path, install_root: Path) -> dict[str, object]:
    install_dir = install_root.expanduser() / skill_dir.name
    return {
        "name": skill_dir.name,
        "archive_path": str(skill_dir),
        "installed": installed_skill_exists(install_dir),
        "install_path": str(install_dir),
    }


def collect_summary(repo: Path, install_root: Path) -> dict[str, object]:
    canonical_repo = repo.expanduser().resolve()
    install_root = install_root.expanduser()
    skills = [collect_active_skill(skill_dir, install_root) for skill_dir in discover_skills(canonical_repo)]
    archived_skills = [
        collect_archived_skill(skill_dir, install_root) for skill_dir in discover_archived_skills(canonical_repo)
    ]
    aggregate_test = canonical_repo / "skills" / "test_all_skills.py"
    shared_tests = canonical_repo / "skills" / "tests"
    active_names = {item["name"] for item in skills}
    archived_names = {item["name"] for item in archived_skills}
    attention = []
    for item in skills:
        if item["missing_required"]:
            attention.append(f"{item['name']}: missing {', '.join(item['missing_required'])}")
        if item["has_run_py"] and not item["has_tests"]:
            attention.append(f"{item['name']}: run.py exists but no test_*.py under tests/")
        if not item["installed"]:
            attention.append(f"{item['name']}: installed copy missing at {item['install_path']}")
        if item["installed"] and not item["install_matches_source"]:
            attention.append(f"{item['name']}: installed copy differs from source")
    for name in sorted(active_names & archived_names):
        attention.append(f"{name}: present in both active skills/ and archive/skills/")
    for item in archived_skills:
        if item["installed"]:
            attention.append(f"{item['name']}: archived skill still installed at {item['install_path']}")
    return {
        "ok": True,
        "repo": str(canonical_repo),
        "install_root": str(install_root),
        "skill_count": len(skills),
        "active_skill_count": len(skills),
        "archived_skill_count": len(archived_skills),
        "skills": skills,
        "archived_skills": archived_skills,
        "aggregate_test": str(aggregate_test) if aggregate_test.exists() else "",
        "shared_tests": shared_tests.exists(),
        "recommended_validation": "python3 -m unittest skills.test_all_skills" if aggregate_test.exists() else "",
        "attention": attention,
    }


def format_markdown(summary: dict[str, object]) -> str:
    lines = [
        f"仓库路径：{summary['repo']}",
        f"安装目录：{summary['install_root']}",
        f"Active Skill 数量：{summary['active_skill_count']}",
        f"归档 Skill 数量：{summary['archived_skill_count']}",
        f"主验证入口：{summary.get('recommended_validation') or '未识别'}",
        f"共享测试目录：{'存在' if summary.get('shared_tests') else '未发现'}",
        "",
        "Active Skill 清单：",
    ]
    for item in summary.get("skills", []):
        markers = []
        if item["has_run_py"]:
            markers.append("run.py")
        if item["has_tests"]:
            markers.append("tests")
        if item["installed"]:
            markers.append("installed")
        if item["install_matches_source"]:
            markers.append("parity")
        suffix = f" ({', '.join(markers)})" if markers else ""
        lines.append(f"- {item['name']}{suffix}")
    lines.append("")
    lines.append("归档 Skill 清单：")
    archived = summary.get("archived_skills") or []
    if archived:
        for item in archived:
            suffix = " (installed-residual)" if item["installed"] else ""
            lines.append(f"- {item['name']}{suffix}")
    else:
        lines.append("- 未发现归档 Skill。")
    lines.append("")
    lines.append("注意事项：")
    attention = summary.get("attention") or []
    if attention:
        lines.extend(f"- {item}" for item in attention)
    else:
        lines.append("- 未识别到缺失附件、未测 run.py 或安装副本差异。")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    summary = collect_summary(Path(args.repo), Path(args.install_root))
    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(summary), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
