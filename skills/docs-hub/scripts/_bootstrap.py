"""docs-hub skill 的初始化、自发现与依赖注入。"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


INIT_STATE_FILE = ".skill-init.json"
REQUIREMENTS_FILE = "requirements-build.txt"
HUB_MARKERS = ("docsets.json", "doc-search/docsets.json", "DocsHub/docsets.json")
RUNTIME_ROOT_ENV = "SKILLS_HUB_RUNTIME_DIR"
RUNTIME_DIR_NAME = "docs-hub"


class HubRootError(ValueError):
    """DocsHub 根目录格式不符合约定。"""


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def runtime_root(_root: Path | None = None) -> Path:
    shared_root = os.getenv(RUNTIME_ROOT_ENV)
    if shared_root:
        return (Path(shared_root).expanduser().resolve() / RUNTIME_DIR_NAME).resolve()

    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.getenv("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return (Path(base) / "skills-hub" / RUNTIME_DIR_NAME).resolve()


def site_packages_path(root: Path | None = None) -> Path:
    return runtime_root(root) / ".deps" / "site-packages"


def legacy_init_state_path(root: Path | None = None) -> Path:
    return (root or skill_root()) / INIT_STATE_FILE


def init_state_path(root: Path | None = None) -> Path:
    return runtime_root(root) / INIT_STATE_FILE


def requirements_path(root: Path | None = None) -> Path:
    return (root or skill_root()) / REQUIREMENTS_FILE


def format_command(parts: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def format_python_command(*parts: str | Path) -> str:
    return format_command([sys.executable, *(str(part) for part in parts)])


def requirements_hash(root: Path | None = None) -> str:
    req = requirements_path(root)
    if not req.exists():
        raise FileNotFoundError(req)
    return hashlib.sha256(req.read_bytes()).hexdigest()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _copytree_once(src: Path, dst: Path) -> Path:
    if dst.exists():
        return dst

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_target = Path(tempfile.mkdtemp(prefix=f"{dst.name}.", dir=dst.parent))
    try:
        shutil.rmtree(tmp_target)
        shutil.copytree(src, tmp_target)
        os.replace(tmp_target, dst)
    finally:
        if tmp_target.exists():
            shutil.rmtree(tmp_target, ignore_errors=True)
    return dst


def _migrate_legacy_init_state(root: Path | None = None) -> dict[str, Any] | None:
    root = root or skill_root()
    runtime_state_path = init_state_path(root)
    state = _read_json(legacy_init_state_path(root))
    if not state:
        return None

    raw_site_packages = str(state.get("site_packages") or root / ".deps" / "site-packages")
    legacy_site_packages = Path(raw_site_packages)
    migrated_state = dict(state)
    migrated_state["skill_root"] = str(root)
    migrated_state["runtime_root"] = str(runtime_root(root))

    if legacy_site_packages.exists():
        try:
            migrated_state["site_packages"] = str(_copytree_once(legacy_site_packages, site_packages_path(root)))
        except OSError:
            return state
    else:
        return state

    write_json_atomic(runtime_state_path, migrated_state)
    return migrated_state


def load_init_state(root: Path | None = None) -> dict[str, Any] | None:
    state = _read_json(init_state_path(root))
    if state is not None:
        return state
    return _migrate_legacy_init_state(root)


def activate_local_site_packages(root: Path | None = None) -> dict[str, Any] | None:
    state = load_init_state(root)
    if not state:
        return None
    site_packages = str(state.get("site_packages") or "")
    if site_packages and site_packages not in sys.path:
        sys.path.insert(0, site_packages)
    return state


def ensure_initialized(command_label: str, root: Path | None = None) -> dict[str, Any]:
    root = root or skill_root()
    state = load_init_state(root)
    init_script = root / "scripts" / "local_doc_init.py"
    init_cmd = format_python_command(init_script, "--skill-root", root)
    if not state:
        raise SystemExit(
            f"[error] $docs-hub 尚未初始化，无法{command_label}。\n"
            f"  请先在 Codex 中执行: $docs-hub init\n"
            f"  若需手动排查，再运行: {init_cmd}"
        )

    site_packages = Path(str(state.get("site_packages") or ""))
    if not site_packages.exists():
        raise SystemExit(
            f"[error] $docs-hub 初始化状态已失效，缺少 site-packages: {site_packages}\n"
            f"  请先在 Codex 中执行: $docs-hub init\n"
            f"  若需手动排查，再运行: {init_cmd}"
        )

    try:
        expected_hash = requirements_hash(root)
    except FileNotFoundError as exc:
        raise SystemExit(
            f"[error] $docs-hub 缺少依赖清单: {exc}\n"
            f"  请确认 skill 安装完整后重新运行: {init_cmd}"
        ) from exc
    if state.get("requirements_hash") != expected_hash:
        raise SystemExit(
            f"[error] $docs-hub 依赖清单已变更，当前初始化状态过期。\n"
            f"  请先在 Codex 中执行: $docs-hub init\n"
            f"  若需手动排查，再运行: {init_cmd}"
        )

    activate_local_site_packages(root)
    return state


def _discover_from_ancestors(start: Path) -> Path | None:
    for base in (start, *start.parents):
        for marker in HUB_MARKERS:
            candidate = base / marker
            if candidate.exists():
                return candidate.parent
    return None


def validate_hub_root(candidate: Path) -> Path:
    candidate = candidate.resolve()
    direct = candidate / "docsets.json"
    if direct.exists():
        return candidate
    nested_doc_search = candidate / "doc-search" / "docsets.json"
    if nested_doc_search.exists():
        return nested_doc_search.parent
    nested_docshub = candidate / "DocsHub" / "docsets.json"
    if nested_docshub.exists():
        return nested_docshub.parent
    raise HubRootError(
        f"指定路径不是有效的 DocsHub 根目录: {candidate}\n"
        "  需要满足以下任一条件：\n"
        "  1. <hub-root>/docsets.json 存在\n"
        "  2. <hub-root>/doc-search/docsets.json 存在\n"
        "  3. <hub-root>/DocsHub/docsets.json 存在"
    )


def _try_validate_hub_root(candidate: Path) -> Path | None:
    try:
        return validate_hub_root(candidate)
    except HubRootError:
        return None


def resolve_init_hub_root(explicit_hub_root: str | None, cwd: Path | None = None) -> Path:
    cwd = cwd or Path.cwd()

    if explicit_hub_root:
        hub = Path(explicit_hub_root).expanduser()
        resolved = hub.resolve() if hub.is_absolute() else (cwd / hub).resolve()
        try:
            return validate_hub_root(resolved)
        except HubRootError as exc:
            raise SystemExit(f"[error] {exc}") from exc

    env_hub = os.getenv("CODEX_DOC_HUB")
    if env_hub:
        resolved = Path(env_hub).expanduser().resolve()
        valid = _try_validate_hub_root(resolved)
        if valid is not None:
            return valid

    discovered = _discover_from_ancestors(cwd.resolve())
    if discovered is not None:
        resolved = discovered.resolve()
        valid = _try_validate_hub_root(resolved)
        if valid is not None:
            return valid

    raise SystemExit(
        "[error] 未找到可用的 DocsHub 根目录。\n"
        "  可选做法：\n"
        "  1. 执行 $docs-hub init <hub-root>\n"
        "  2. 设置环境变量 CODEX_DOC_HUB\n"
        "  3. 在当前工作区或其祖先目录放置 docsets.json / doc-search/docsets.json / DocsHub/docsets.json"
    )


def resolve_query_hub_root(
    explicit_hub_root: str | None,
    saved_hub_root: str | None,
    cwd: Path | None = None,
) -> Path:
    cwd = cwd or Path.cwd()

    if explicit_hub_root:
        hub = Path(explicit_hub_root).expanduser()
        resolved = hub.resolve() if hub.is_absolute() else (cwd / hub).resolve()
        valid = _try_validate_hub_root(resolved)
        if valid is not None:
            return valid

    if saved_hub_root:
        valid = _try_validate_hub_root(Path(saved_hub_root).expanduser())
        if valid is not None:
            return valid

    env_hub = os.getenv("CODEX_DOC_HUB")
    if env_hub:
        valid = _try_validate_hub_root(Path(env_hub).expanduser().resolve())
        if valid is not None:
            return valid

    discovered = _discover_from_ancestors(cwd.resolve())
    if discovered is not None:
        valid = _try_validate_hub_root(discovered.resolve())
        if valid is not None:
            return valid

    raise SystemExit(
        "[error] 未找到可用的 DocsHub 根目录。\n"
        "  查询时按以下顺序检查：\n"
        "  1. 显式 --hub-root\n"
        "  2. 上次 init 记录的 DocsHub 根目录\n"
        "  3. 环境变量 CODEX_DOC_HUB\n"
        "  4. 当前工作区及其祖先目录中的 docsets.json / doc-search/docsets.json / DocsHub/docsets.json"
    )
