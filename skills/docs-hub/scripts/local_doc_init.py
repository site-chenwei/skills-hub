"""初始化 docs-hub skill 自身依赖。"""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import (  # noqa: E402
    REQUIREMENTS_FILE,
    current_python_version,
    dependency_cache_problem,
    format_python_command,
    init_state_path,
    load_init_state,
    requirements_hash,
    resolve_init_hub_root,
    runtime_root,
    site_packages_path,
    skill_root,
    write_json_atomic,
)
from catalog import catalog_path, discover_missing_docsets, update_catalog  # noqa: E402


def deps_site_packages(root: Path) -> Path:
    return site_packages_path(root)


def install_requirements(site_packages: Path, req_path: Path) -> str:
    uv = shutil.which("uv")
    if uv:
        subprocess.run(
            [uv, "pip", "install", "--python", sys.executable, "--upgrade", "--target", str(site_packages), "-r", str(req_path)],
            check=True,
        )
        return "uv"

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--target", str(site_packages), "-r", str(req_path)],
        check=True,
    )
    return "python -m pip"


def install_requirements_atomic(root: Path, req_path: Path) -> tuple[Path, str]:
    deps_root = root / ".deps"
    deps_root.mkdir(parents=True, exist_ok=True)
    final_target = deps_site_packages(root)
    tmp_target = Path(tempfile.mkdtemp(prefix="site-packages.", dir=deps_root))
    backup_target = deps_root / ".site-packages.backup"

    try:
        installer = install_requirements(tmp_target, req_path)
    except Exception:  # noqa: BLE001
        shutil.rmtree(tmp_target, ignore_errors=True)
        raise

    if backup_target.exists():
        shutil.rmtree(backup_target, ignore_errors=True)

    try:
        if final_target.exists():
            final_target.rename(backup_target)
        tmp_target.rename(final_target)
    except Exception:  # noqa: BLE001
        if not final_target.exists() and backup_target.exists():
            backup_target.rename(final_target)
        shutil.rmtree(tmp_target, ignore_errors=True)
        raise
    else:
        shutil.rmtree(backup_target, ignore_errors=True)
        return final_target, installer


def reuse_existing_site_packages(root: Path, _req_path: Path) -> tuple[Path, str] | None:
    state = load_init_state(root)
    if not state:
        return None
    if dependency_cache_problem(state, root):
        return None

    site_packages = Path(str(state["site_packages"]))
    installer = str(state.get("installer") or "cached")
    return site_packages, installer


def activate_site_packages(site_packages: Path) -> None:
    site_packages_str = str(site_packages)
    if site_packages_str not in sys.path:
        sys.path.insert(0, site_packages_str)


def load_docsets_config(hub_root: Path) -> dict[str, Any]:
    cfg_path = hub_root / "docsets.json"
    if not cfg_path.exists():
        raise SystemExit(f"[error] DocsHub 缺少 docsets.json: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_build_module():
    return importlib.import_module("build_docset_index")


def detect_index_actions(hub_root: Path, build_module) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any], bool]]]:
    cfg = load_docsets_config(hub_root)
    defaults = cfg.get("defaults", {})
    actions: list[tuple[str, dict[str, Any], bool]] = []

    for docset in cfg.get("docsets", []):
        try:
            docset_id = build_module.safe_docset_id(docset)
            build_module.resolve_docset_root(hub_root, docset)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"[error] docset 配置无效: {exc}") from exc
        if not docset_id:
            continue
        db_path = build_module.docset_index_path(hub_root, docset)
        if not db_path.exists():
            actions.append(("missing", docset, False))
            continue

        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(db_path)
            current_signature = build_module.meta_value(conn, "build_signature")
        except sqlite3.Error:
            actions.append(("invalid", docset, True))
            continue
        finally:
            if conn is not None:
                conn.close()

        expected_signature = build_module.compute_build_signature(build_module.merge_config(defaults, docset))
        if current_signature != expected_signature:
            actions.append(("stale", docset, False))

    return defaults, actions


def build_required_indexes(hub_root: Path, defaults: dict[str, Any], actions: list[tuple[str, dict[str, Any], bool]], build_module) -> None:
    if not actions:
        print("[init] 索引已存在且与当前 build 逻辑一致，无需补建")
        return

    grouped: dict[str, list[str]] = {}
    for reason, docset, _ in actions:
        grouped.setdefault(reason, []).append(docset["id"])

    for reason in ("missing", "stale", "invalid"):
        if grouped.get(reason):
            print(f"[init] 需要处理的 {reason} 索引: {', '.join(grouped[reason])}")

    for reason, docset, rebuild in actions:
        verb = "重建" if rebuild or reason != "missing" else "构建"
        print(f"[init] 自动{verb}索引: {docset['id']} ({reason})")
        try:
            stats = build_module.build_docset(hub_root, docset, defaults, rebuild=rebuild)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"[error] 自动{verb}索引失败: {docset['id']}: {exc}") from exc
        print(f"  stats: {stats}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-root", default=None, help="skill 根目录；默认按当前脚本位置推断")
    ap.add_argument("--hub-root", default=None, help="DocsHub 根目录；未传时尝试从 env/当前工作区自动发现")
    ap.add_argument("--refresh-deps", action="store_true", help="忽略依赖缓存，强制重新安装 skill 依赖")
    args = ap.parse_args()

    root = Path(args.skill_root).resolve() if args.skill_root else skill_root()
    runtime_dir = runtime_root(root)
    hub_root = resolve_init_hub_root(args.hub_root)
    req_path = root / REQUIREMENTS_FILE
    if not req_path.exists():
        raise SystemExit(f"[error] 缺少依赖清单: {req_path}")

    reused = None if args.refresh_deps else reuse_existing_site_packages(root, req_path)
    if reused is not None:
        site_packages, installer = reused
        print(f"[init] 复用已有 skill 依赖: {site_packages}")
    else:
        print(f"[init] 安装 skill 依赖到本地 runtime 目录: {deps_site_packages(runtime_dir)}")
        site_packages, installer = install_requirements_atomic(runtime_dir, req_path)
    activate_site_packages(site_packages)

    discovered = discover_missing_docsets(hub_root)
    if discovered:
        print("[init] 自动发现 docset: " + ", ".join(str(item["id"]) for item in discovered))

    state = {
        "initialized_at": datetime.now(timezone.utc).isoformat(),
        "skill_root": str(root),
        "installer": installer,
        "installer_python": sys.executable,
        "site_packages": str(site_packages),
        "hub_root": str(hub_root),
        "runtime_root": str(runtime_dir),
        "requirements_file": REQUIREMENTS_FILE,
        "requirements_hash": requirements_hash(root),
        "python_version": current_python_version(),
    }
    problem = dependency_cache_problem(state, root)
    if problem:
        raise SystemExit(f"[error] skill 依赖缓存校验失败: {problem}")

    build_module = load_build_module()
    defaults, actions = detect_index_actions(hub_root, build_module)
    build_required_indexes(hub_root, defaults, actions, build_module)
    update_catalog(hub_root)
    print(f"[init] 已更新资料目录: {catalog_path(hub_root)}")
    state_path = init_state_path(root)
    write_json_atomic(state_path, state)
    print(f"[init] 完成: {state_path}")
    print(f"[init] 已记录 DocsHub 根目录: {hub_root}")
    print(f"[init] 后续可直接运行: {format_python_command(root / 'run.py', 'search', '<keywords>')}")


if __name__ == "__main__":
    main()
