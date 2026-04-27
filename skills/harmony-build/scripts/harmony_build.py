#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
CACHE_SCHEMA_VERSION = 3
SKILL_RUNTIME_ROOT_ENV = "SKILLS_HUB_RUNTIME_DIR"
SKILL_CACHE_DIR_NAME = "harmony-build"
HVIGOR_TASK_TIMEOUT_SECONDS = 900
HVIGOR_TASK_LIST_TIMEOUT_SECONDS = 120
HVIGOR_PREFLIGHT_TIMEOUT_SECONDS = HVIGOR_TASK_LIST_TIMEOUT_SECONDS
HVIGOR_OUTPUT_TAIL_LINES = 80
HVIGOR_OUTPUT_TAIL_BYTES = 128 * 1024
HILOG_DEFAULT_BUFFER_LINES = 500
HILOG_DEFAULT_MAX_LINES = 200
HILOG_DEFAULT_TIMEOUT_SECONDS = 5
PROJECT_MARKERS = (
    "build-profile.json5",
    "hvigorfile.ts",
    "hvigorfile.js",
    "oh-package.json5",
    "AppScope/app.json5",
)
SDK_ENV_KEYS = ("DEVECO_SDK_HOME", "HOS_SDK_HOME", "OHOS_SDK_HOME")
ENV_FAILURE_MARKERS = (
    "NODE_HOME is not set and no 'node' command could be found in your PATH",
    "Invalid value of 'DEVECO_SDK_HOME' in the system environment path",
    "SDK component missing",
    "Cannot find module",
    "command not found",
    "Permission denied",
    "not executable",
)
VERSION_PROBES = {
    "node": ("node_path", ("--version",)),
    "java": ("java_path", ("-version",)),
    "ohpm": ("ohpm_path", ("--version",)),
    "hdc": ("hdc_path", ("-v",)),
}
SDK_COMPONENT_MARKERS = ("ets", "js", "native", "toolchains", "kits", "api")
MODULE_CONFIG_FILES = {"build-profile.json5", "oh-package.json5", "hvigorfile.ts", "hvigorfile.js"}
RUNTIME_OS_RE = re.compile(r"""["']?runtimeOS["']?\s*:\s*["']([^"']+)["']""")
PROJECT_CONFIG_IGNORED_DIRS = {".git", ".hvigor", "build", "node_modules", "oh_modules"}
TASK_LINE_RE = re.compile(r"^\s*([:\w.-]+)\s+-\s+")
APP_BUNDLE_NAME_RE = re.compile(r"""["']?bundleName["']?\s*:\s*["']([^"']+)["']""")
HILOG_LEVELS = {"DEBUG", "INFO", "WARN", "ERROR", "FATAL", "D", "I", "W", "E", "F"}
BUILD_TASK_PREFERENCE = (
    "assembleHap",
    "assembleApp",
    "PackageApp",
    "SignPackagesFromApp",
    "build",
)


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def detect_runtime() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    release = platform.uname().release.lower()
    if "microsoft" in release or os.environ.get("WSL_DISTRO_NAME"):
        return "wsl"
    return "linux"


RUNTIME = detect_runtime()


def unique_values(values):
    seen = set()
    result = []
    for item in values:
        if item is None:
            continue
        normalized = str(item).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def non_empty_lines(text: str, max_lines: int | None = None) -> list[str]:
    lines = [line for line in strip_ansi(text).splitlines() if line.strip()]
    if max_lines is not None and len(lines) > max_lines:
        return lines[-max_lines:]
    return lines


def combine_process_output(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
    parts = []
    for value in (stdout, stderr):
        if value is None:
            continue
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        if value.strip():
            parts.append(value.strip())
    return "\n".join(parts)


def strip_json5_comments(text: str) -> str:
    result = []
    index = 0
    quote = None
    escaped = False
    length = len(text)

    while index < length:
        char = text[index]
        next_char = text[index + 1] if index + 1 < length else ""

        if quote:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue

        if char in {"'", '"'}:
            quote = char
            result.append(char)
            index += 1
            continue

        if char == "/" and next_char == "/":
            index += 2
            while index < length and text[index] not in "\r\n":
                index += 1
            continue

        if char == "/" and next_char == "*":
            index += 2
            while index < length - 1 and not (text[index] == "*" and text[index + 1] == "/"):
                if text[index] in "\r\n":
                    result.append(text[index])
                index += 1
            index = min(index + 2, length)
            continue

        result.append(char)
        index += 1

    return "".join(result)


def now_iso_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def cache_root_dir() -> Path:
    shared_root = os.environ.get(SKILL_RUNTIME_ROOT_ENV)
    if shared_root:
        return (Path(shared_root).expanduser().resolve() / SKILL_CACHE_DIR_NAME).resolve()

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return (Path(base) / "skills-hub" / SKILL_CACHE_DIR_NAME).resolve()


def legacy_cache_root_dir() -> Path | None:
    if os.environ.get(SKILL_RUNTIME_ROOT_ENV):
        return None

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "codex" / SKILL_CACHE_DIR_NAME


def resolve_repo_paths(repo_arg: str | None) -> dict:
    repo_input = repo_arg or os.getcwd()
    repo_local = Path(repo_input).expanduser().resolve()
    return {
        "input": repo_input,
        "local_path": str(repo_local),
        "local_exists": repo_local.exists(),
    }


def repo_identity(repo_info: dict) -> str:
    candidate = repo_info.get("local_path") or repo_info.get("input") or "unknown-repo"
    return str(Path(candidate).expanduser().resolve())


def cache_file_for_repo(repo_info: dict) -> Path:
    repo_hash = hashlib.sha256(repo_identity(repo_info).encode("utf-8")).hexdigest()[:16]
    return cache_root_dir() / f"{repo_hash}.json"


def legacy_cache_file_for_repo(repo_info: dict) -> Path | None:
    legacy_root = legacy_cache_root_dir()
    if legacy_root is None:
        return None
    repo_hash = hashlib.sha256(repo_identity(repo_info).encode("utf-8")).hexdigest()[:16]
    return legacy_root / f"{repo_hash}.json"


def migrate_legacy_cache_file(repo_info: dict, cache_path: Path) -> None:
    if cache_path.exists():
        return

    legacy_path = legacy_cache_file_for_repo(repo_info)
    if legacy_path is None or not legacy_path.exists():
        return

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy_path, cache_path)


def build_cache_metadata(
    path: Path | None,
    source: str,
    *,
    saved: bool,
    saved_at: str | None = None,
    invalid_reason: str | None = None,
) -> dict:
    metadata = {
        "source": source,
        "saved": saved,
    }
    if path:
        metadata["path"] = str(path)
    if saved_at:
        metadata["saved_at"] = saved_at
    if invalid_reason:
        metadata["invalid_reason"] = invalid_reason
    return metadata


def strip_cache_metadata(result: dict) -> dict:
    payload = dict(result)
    payload.pop("cache", None)
    return payload


def host_path_exists(path_text: str | None) -> bool:
    if not path_text:
        return False
    return Path(path_text).expanduser().exists()


def is_executable_file(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    if os.name == "nt":
        return True
    return os.access(path, os.X_OK)


def repo_hvigorw_not_executable(repo: Path) -> bool:
    wrapper = repo / "hvigorw"
    return wrapper.exists() and wrapper.is_file() and not is_executable_file(wrapper)


def hvigorw_permission_hint(repo: Path) -> str | None:
    if not repo_hvigorw_not_executable(repo):
        return None
    return f"Repo wrapper exists but is not executable: {repo / 'hvigorw'}. Run from the repo root: chmod +x hvigorw"


def hvigor_not_executable_message(hvigor_path: str, repo_local: str | None = None) -> str:
    message = f"hvigor executable is missing or not executable: {hvigor_path}"
    hvigor = Path(hvigor_path)
    if hvigor.name == "hvigorw":
        message += "\nRun from the repo root: chmod +x hvigorw"
    elif repo_local and (Path(repo_local) / "hvigorw").exists():
        message += "\nIf the repo wrapper is present, run from the repo root: chmod +x hvigorw"
    return message


def is_cached_detection_usable(result: dict | None, repo_info: dict) -> tuple[bool, str | None]:
    if not isinstance(result, dict):
        return False, "invalid_payload"
    if result.get("version") not in (None, CACHE_SCHEMA_VERSION):
        return False, "schema_mismatch"

    cached_repo = result.get("repo") or {}
    resolved = result.get("resolved") or {}
    if repo_identity(cached_repo) != repo_identity(repo_info):
        return False, "repo_mismatch"
    if not result.get("ready"):
        return False, "not_ready"
    runtime_os = read_project_runtime_os(Path(repo_info.get("local_path") or ""))
    sdk_family = sdk_family_from_runtime_os(runtime_os)
    sdk_home = resolved.get("sdk_home")
    if sdk_family == "harmonyos" and sdk_root_kind(Path(sdk_home or "")) != "harmonyos":
        return False, "sdk_family_mismatch"

    existence_checks = [
        ("repo_local_path", cached_repo.get("local_path")),
        ("sdk_home", sdk_home),
    ]
    for label, path_text in existence_checks:
        if not host_path_exists(path_text):
            return False, f"missing_{label}"

    executable_checks = [
        ("node_path", resolved.get("node_path")),
        ("hvigor_path", resolved.get("hvigor_path")),
    ]
    for label, path_text in executable_checks:
        if not host_path_exists(path_text):
            return False, f"missing_{label}"
        if not is_executable_file(Path(path_text).expanduser()):
            return False, f"not_executable_{label}"

    if not (result.get("preflight") or {}).get("success"):
        return False, "missing_ready_preflight"
    return True, None


def load_cached_detection(repo_info: dict) -> tuple[dict | None, dict]:
    cache_path = cache_file_for_repo(repo_info)
    migrate_legacy_cache_file(repo_info, cache_path)
    if not cache_path.exists():
        return None, build_cache_metadata(cache_path, "miss", saved=False)

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return None, build_cache_metadata(
            cache_path,
            "stale",
            saved=False,
            invalid_reason=f"unreadable_cache:{error}",
        )

    if payload.get("version") != CACHE_SCHEMA_VERSION:
        return None, build_cache_metadata(
            cache_path,
            "stale",
            saved=False,
            saved_at=payload.get("saved_at"),
            invalid_reason="schema_mismatch",
        )

    result = payload.get("result")
    usable, invalid_reason = is_cached_detection_usable(result, repo_info)
    if not usable:
        return None, build_cache_metadata(
            cache_path,
            "stale",
            saved=False,
            saved_at=payload.get("saved_at"),
            invalid_reason=invalid_reason,
        )

    hydrated = dict(result)
    hydrated["cache"] = build_cache_metadata(
        cache_path,
        "cache",
        saved=True,
        saved_at=payload.get("saved_at"),
    )
    return hydrated, hydrated["cache"]


def save_cached_detection(result: dict) -> dict:
    cache_path = cache_file_for_repo(result["repo"])
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    saved_at = now_iso_utc()
    payload = {
        "version": CACHE_SCHEMA_VERSION,
        "saved_at": saved_at,
        "result": strip_cache_metadata(result),
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return build_cache_metadata(cache_path, "fresh", saved=True, saved_at=saved_at)


def which_all(command_name: str) -> list[str]:
    found = []
    first = shutil.which(command_name)
    if first:
        found.append(str(Path(first).resolve()))

    path_parts = os.environ.get("PATH", "").split(os.pathsep)
    executable_names = [command_name]
    if os.name == "nt" and not Path(command_name).suffix:
        executable_names.extend(f"{command_name}{ext.lower()}" for ext in os.environ.get("PATHEXT", ".EXE;.BAT;.CMD").split(";"))

    for raw_dir in path_parts:
        if not raw_dir:
            continue
        base = Path(raw_dir).expanduser()
        for name in executable_names:
            candidate = base / name
            if is_executable_file(candidate):
                found.append(str(candidate.resolve()))
    return unique_values(found)


def candidate_deveco_apps() -> list[str]:
    candidates = [
        Path("/Applications/DevEco-Studio.app"),
        Path("/Applications/DevEco Studio.app"),
        Path.home() / "Applications" / "DevEco-Studio.app",
        Path.home() / "Applications" / "DevEco Studio.app",
    ]
    for base in [Path("/Applications"), Path.home() / "Applications"]:
        if base.exists():
            candidates.extend(sorted(base.glob("DevEco*.app")))
    return unique_values(str(path.resolve()) for path in candidates if path.exists())


def detect_project_markers(repo: Path) -> list[str]:
    markers = []
    if not repo.exists() or not repo.is_dir():
        return markers
    for marker in PROJECT_MARKERS:
        if (repo / marker).exists():
            markers.append(marker)
    return markers


def iter_project_config_files(repo: Path, filename: str):
    if not repo.exists() or not repo.is_dir():
        return
    direct = repo / filename
    if direct.is_file():
        yield direct
    for root_text, dirnames, filenames in os.walk(repo):
        dirnames[:] = [dirname for dirname in dirnames if dirname not in PROJECT_CONFIG_IGNORED_DIRS]
        root = Path(root_text)
        if root == repo or filename not in filenames:
            continue
        yield root / filename


def read_project_runtime_os(repo: Path) -> str | None:
    for path in iter_project_config_files(repo, "build-profile.json5") or []:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = RUNTIME_OS_RE.search(strip_json5_comments(text))
        if match:
            return match.group(1).strip()
    return None


def candidate_node_paths() -> list[str]:
    candidates = []
    node_home = os.environ.get("NODE_HOME")
    if node_home:
        root = Path(node_home).expanduser()
        candidates.extend([root / "bin" / "node", root / "node"])
    candidates.extend(Path(path) for path in which_all("node"))
    candidates.extend(
        [
            Path("/opt/homebrew/bin/node"),
            Path("/usr/local/bin/node"),
            Path("/usr/bin/node"),
        ]
    )
    return unique_values(str(path.resolve()) for path in candidates if path.exists())


def node_home_from_path(node_path: str | None) -> str | None:
    if not node_path:
        return None
    path = Path(node_path)
    if path.parent.name == "bin":
        return str(path.parent.parent)
    return str(path.parent)


def resolve_node() -> tuple[str | None, str | None, list[str]]:
    candidates = candidate_node_paths()
    node_path = next((item for item in candidates if is_executable_file(Path(item))), None)
    return node_home_from_path(node_path), node_path, candidates


def candidate_java_paths() -> list[str]:
    candidates = []
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidates.append(Path(java_home).expanduser() / "bin" / "java")
    candidates.extend(Path(path) for path in which_all("java"))
    candidates.append(Path("/usr/bin/java"))
    return unique_values(str(path.resolve()) for path in candidates if path.exists())


def macos_java_home_helper_path() -> Path:
    return Path("/usr/libexec/java_home")


def macos_java_home_helper_exists() -> bool:
    return macos_java_home_helper_path().exists()


def resolve_macos_java_home() -> str | None:
    if RUNTIME != "macos":
        return None
    helper = macos_java_home_helper_path()
    if not macos_java_home_helper_exists():
        return None
    try:
        result = subprocess.run(
            [str(helper)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    java_home = result.stdout.strip().splitlines()
    return java_home[0].strip() if java_home and java_home[0].strip() else None


def java_home_from_path(java_path: str | None) -> str | None:
    explicit_java_home = os.environ.get("JAVA_HOME")
    if explicit_java_home:
        return explicit_java_home
    if not java_path:
        return None
    if RUNTIME == "macos" and Path(java_path).as_posix() == "/usr/bin/java":
        return resolve_macos_java_home()
    path = Path(java_path)
    if path.parent.name == "bin":
        return str(path.parent.parent)
    return None


def resolve_java() -> tuple[str | None, str | None, list[str]]:
    candidates = candidate_java_paths()
    java_path = next((item for item in candidates if is_executable_file(Path(item))), None)
    return java_home_from_path(java_path), java_path, candidates


def looks_like_sdk_root(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    child_names = {child.name for child in path.iterdir() if child.is_dir()}
    return bool(set(SDK_COMPONENT_MARKERS) & child_names)


def sdk_component_root_has_manifest(path: Path) -> bool:
    manifests = ("uni-package.json", "oh-uni-package.json")
    return any((path / component / manifest).is_file() for component in SDK_COMPONENT_MARKERS for manifest in manifests)


def looks_like_openharmony_sdk_root(path: Path) -> bool:
    return looks_like_sdk_root(path) and sdk_component_root_has_manifest(path)


def harmonyos_sdk_component_roots(path: Path) -> tuple[Path, Path]:
    default_root = path / "default"
    if (default_root / "hms").is_dir() or (default_root / "openharmony").is_dir():
        return default_root / "hms", default_root / "openharmony"
    return path / "hms", path / "openharmony"


def looks_like_harmonyos_sdk_root(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    hms_root, openharmony_root = harmonyos_sdk_component_roots(path)
    return looks_like_sdk_root(hms_root) and looks_like_sdk_root(openharmony_root)


def sdk_root_kind(path: Path) -> str | None:
    if looks_like_harmonyos_sdk_root(path):
        return "harmonyos"
    if looks_like_openharmony_sdk_root(path):
        return "openharmony"
    return None


def sdk_family_from_runtime_os(runtime_os: str | None) -> str | None:
    if not runtime_os:
        return None
    normalized = runtime_os.strip().lower()
    if normalized == "harmonyos":
        return "harmonyos"
    if normalized == "openharmony":
        return "openharmony"
    return None


def candidate_sdk_roots() -> list[str]:
    candidates = []
    for key in SDK_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            candidates.append(Path(value).expanduser())

    home = Path.home()
    candidates.extend(
        [
            home / "Library" / "OpenHarmony" / "Sdk",
            home / "Library" / "Huawei" / "Sdk",
            home / "Library" / "Application Support" / "Huawei" / "DevEcoStudio" / "Sdk",
            home / "Library" / "Application Support" / "Huawei" / "DevEco Studio" / "Sdk",
        ]
    )
    for app_text in candidate_deveco_apps():
        app = Path(app_text)
        candidates.extend(
            [
                app / "Contents" / "sdk",
                app / "Contents" / "Sdk",
            ]
        )

    expanded = []
    for candidate in unique_values(str(path.resolve()) for path in candidates if path.exists()):
        path = Path(candidate)
        kind = sdk_root_kind(path)
        if kind:
            expanded.append(str(path))
            if kind == "harmonyos":
                continue
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_dir() and sdk_root_kind(child):
                    expanded.append(str(child.resolve()))
    return unique_values(expanded)


def select_sdk_root(candidates: list[str], sdk_family: str | None) -> str | None:
    if sdk_family == "harmonyos":
        return next((item for item in candidates if sdk_root_kind(Path(item)) == "harmonyos"), None)
    if sdk_family == "openharmony":
        return next(
            (item for item in candidates if sdk_root_kind(Path(item)) == "openharmony"),
            next((item for item in candidates if sdk_root_kind(Path(item)) == "harmonyos"), None),
        )
    return candidates[0] if candidates else None


def resolve_sdk_root(repo: Path | None = None) -> tuple[str | None, list[str]]:
    candidates = candidate_sdk_roots()
    runtime_os = read_project_runtime_os(repo) if repo else None
    return select_sdk_root(candidates, sdk_family_from_runtime_os(runtime_os)), candidates


def candidate_hvigor_paths(repo: Path) -> list[str]:
    candidates = [
        repo / "hvigorw",
        repo / "hvigor",
    ]
    candidates.extend(Path(path) for path in which_all("hvigorw"))
    candidates.extend(Path(path) for path in which_all("hvigor"))

    for app_text in candidate_deveco_apps():
        app = Path(app_text)
        candidates.extend(
            [
                app / "Contents" / "tools" / "hvigor" / "bin" / "hvigorw",
                app / "Contents" / "tools" / "hvigor" / "bin" / "hvigor",
            ]
        )

    return unique_values(str(path.resolve()) for path in candidates if path.exists())


def resolve_hvigor_path(repo: Path) -> tuple[str | None, list[str], str | None]:
    candidates = candidate_hvigor_paths(repo)
    if repo_hvigorw_not_executable(repo):
        return None, candidates, "repo-wrapper-not-executable"
    for item in candidates:
        path = Path(item)
        if is_executable_file(path):
            kind = "repo-wrapper" if path.parent == repo else "path"
            return item, candidates, kind
    return None, candidates, None


def resolve_optional_tool(command_name: str) -> tuple[str | None, list[str]]:
    candidates = which_all(command_name)
    return (candidates[0] if candidates else None), candidates


def hdc_candidates_from_sdk_root(sdk_root: Path) -> list[Path]:
    candidates = [
        sdk_root / "toolchains" / "hdc",
        sdk_root / "openharmony" / "toolchains" / "hdc",
        sdk_root / "hms" / "toolchains" / "hdc",
    ]
    hms_root, openharmony_root = harmonyos_sdk_component_roots(sdk_root)
    candidates.extend(
        [
            openharmony_root / "toolchains" / "hdc",
            hms_root / "toolchains" / "hdc",
        ]
    )
    default_root = sdk_root / "default"
    candidates.extend(
        [
            default_root / "openharmony" / "toolchains" / "hdc",
            default_root / "hms" / "toolchains" / "hdc",
        ]
    )
    return candidates


def candidate_hdc_paths(sdk_home: str | None = None) -> list[str]:
    candidates = [Path(path) for path in which_all("hdc")]
    if sdk_home:
        candidates.extend(hdc_candidates_from_sdk_root(Path(sdk_home).expanduser()))

    for sdk_text in candidate_sdk_roots():
        candidates.extend(hdc_candidates_from_sdk_root(Path(sdk_text)))

    for app_text in candidate_deveco_apps():
        app = Path(app_text)
        candidates.extend(hdc_candidates_from_sdk_root(app / "Contents" / "sdk"))

    return unique_values(str(path.resolve()) for path in candidates if path.exists())


def resolve_hdc_path(sdk_home: str | None = None) -> tuple[str | None, list[str]]:
    candidates = candidate_hdc_paths(sdk_home)
    hdc_path = next((item for item in candidates if is_executable_file(Path(item))), None)
    return hdc_path, candidates


def run_short_command(args: list[str], timeout_seconds: int = 10) -> dict:
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        return {
            "success": False,
            "exit_code": 124,
            "output": combine_process_output(error.stdout, error.stderr),
            "timed_out": True,
        }
    except OSError as error:
        return {
            "success": False,
            "exit_code": getattr(error, "errno", 1) or 1,
            "output": str(error),
            "timed_out": False,
        }

    return {
        "success": result.returncode == 0,
        "exit_code": result.returncode,
        "output": combine_process_output(result.stdout, result.stderr),
        "timed_out": False,
    }


def probe_tool_version(name: str, path_text: str | None, version_args: tuple[str, ...]) -> dict:
    if not path_text:
        return {
            "path": None,
            "available": False,
            "version": None,
            "exit_code": None,
            "timed_out": False,
        }

    outcome = run_short_command([path_text, *version_args])
    return {
        "path": path_text,
        "available": outcome["success"],
        "version": "\n".join(non_empty_lines(outcome["output"], max_lines=4)) or None,
        "exit_code": outcome["exit_code"],
        "timed_out": outcome["timed_out"],
    }


def collect_tool_versions(resolved: dict) -> dict:
    versions = {}
    for name, (path_key, args) in VERSION_PROBES.items():
        versions[name] = probe_tool_version(name, resolved.get(path_key), args)
    return versions


def collect_macos_java_home_verbose() -> dict:
    if RUNTIME != "macos":
        return {
            "available": False,
            "reason": "non_macos_runtime",
            "summary": [],
        }

    helper = macos_java_home_helper_path()
    if not macos_java_home_helper_exists():
        return {
            "available": False,
            "reason": "helper_missing",
            "summary": [],
        }

    outcome = run_short_command([str(helper), "-V"])
    return {
        "available": outcome["success"],
        "exit_code": outcome["exit_code"],
        "timed_out": outcome["timed_out"],
        "summary": non_empty_lines(outcome["output"], max_lines=12),
    }


def sdk_api_from_path(path: Path) -> str | None:
    name = path.name
    if re.fullmatch(r"\d+(?:\.\d+)?", name):
        return name
    return None


def describe_sdk_root(path_text: str) -> dict:
    path = Path(path_text).expanduser()
    entry = {
        "path": path_text,
        "exists": path.exists(),
        "api": sdk_api_from_path(path),
        "kind": sdk_root_kind(path),
        "components": [],
    }
    if not path.exists() or not path.is_dir():
        return entry

    child_names = {child.name for child in path.iterdir() if child.is_dir()}
    entry["components"] = [name for name in SDK_COMPONENT_MARKERS if name in child_names]
    return entry


def collect_sdk_diagnostics(sdk_home: str | None, sdk_candidates: list[str]) -> dict:
    candidate_paths = unique_values([sdk_home, *sdk_candidates])
    return {
        "selected": sdk_home,
        "candidates": [describe_sdk_root(path) for path in candidate_paths],
    }


def build_doctor_report_from_detection(detection: dict) -> dict:
    resolved = detection.get("resolved") or {}
    candidates = detection.get("candidates") or {}
    return {
        "tools": collect_tool_versions(resolved),
        "macos_java_home": collect_macos_java_home_verbose(),
        "sdk": collect_sdk_diagnostics(resolved.get("sdk_home"), candidates.get("sdk_home") or []),
        "deveco": {
            "selected": resolved.get("deveco_app"),
            "candidates": candidates.get("deveco_app") or [],
        },
    }


def build_doctor_report(repo_arg: str | None) -> dict:
    detection = detect_environment_for_repo(resolve_repo_paths(repo_arg), preflight=False)
    return {
        "detection": detection,
        "doctor": build_doctor_report_from_detection(detection),
    }


def print_tool_version(name: str, info: dict) -> None:
    path_text = info.get("path") or "NOT FOUND"
    print(f"{name}: {path_text}")
    version = info.get("version")
    if version:
        for line in version.splitlines():
            print(f"  {line}")
    elif info.get("exit_code") is not None:
        print(f"  version probe failed with exit code {info['exit_code']}")


def print_doctor_report(report: dict) -> None:
    print("Doctor:")
    tools = report.get("tools") or {}
    for name in ("node", "java", "ohpm", "hdc"):
        print_tool_version(name, tools.get(name) or {})

    java_home = report.get("macos_java_home") or {}
    print("macOS java_home -V:")
    if java_home.get("summary"):
        for line in java_home["summary"]:
            print(f"  {line}")
    else:
        print(f"  {java_home.get('reason') or 'NOT AVAILABLE'}")

    sdk = report.get("sdk") or {}
    print(f"Harmony SDK selected: {sdk.get('selected') or 'NOT FOUND'}")
    for candidate in sdk.get("candidates") or []:
        parts = [candidate["path"]]
        if candidate.get("kind"):
            parts.append(f"kind={candidate['kind']}")
        if candidate.get("api"):
            parts.append(f"api={candidate['api']}")
        if candidate.get("components"):
            parts.append(f"components={','.join(candidate['components'])}")
        if not candidate.get("exists"):
            parts.append("missing")
        print(f"  {'; '.join(parts)}")

    deveco = report.get("deveco") or {}
    print(f"DevEco Studio selected: {deveco.get('selected') or 'NOT FOUND'}")
    for candidate in deveco.get("candidates") or []:
        print(f"  {candidate}")


def normalize_changed_path(repo: Path, path_text: str) -> tuple[str, list[str]]:
    path = Path(path_text).expanduser()
    if path.is_absolute():
        try:
            display = str(path.resolve().relative_to(repo.resolve()))
        except ValueError:
            display = str(path)
    else:
        display = str(path)
    parts = [part for part in Path(display).parts if part not in ("", os.sep)]
    return display.replace("\\", "/"), parts


def module_from_path_parts(parts: list[str]) -> str | None:
    if "src" in parts:
        index = parts.index("src")
        if index > 0:
            return parts[index - 1]
    if parts and parts[-1] in MODULE_CONFIG_FILES and len(parts) > 1:
        return parts[-2]
    return None


def classify_changed_path(parts: list[str]) -> str:
    lowered = [part.lower() for part in parts]
    file_name = lowered[-1] if lowered else ""
    if "ets" in lowered or file_name.endswith(".ets"):
        return "ets"
    if "resources" in lowered or "resource" in lowered:
        return "resources"
    if file_name in MODULE_CONFIG_FILES:
        return "module_config" if len(parts) > 1 else "project_config"
    return "unknown"


def recommendation_for_path(repo: Path, path_text: str) -> dict:
    display, parts = normalize_changed_path(repo, path_text)
    module = module_from_path_parts(parts)
    kind = classify_changed_path(parts)

    if kind in {"ets", "resources"} and module:
        return {
            "path": display,
            "kind": kind,
            "module": module,
            "task_template": f":{module}:assembleHap",
            "confidence": "template",
            "requires_task_listing": False,
            "reason": "页面、ArkTS 或资源改动通常优先选择对应模块级公开 hvigor 任务；实际任务名需以项目 tasks 列表为准。",
        }

    if kind == "module_config" and module:
        return {
            "path": display,
            "kind": kind,
            "module": module,
            "task_template": f":{module}:assembleHap",
            "confidence": "template",
            "requires_task_listing": False,
            "reason": "模块构建配置或依赖文件变更，优先选择模块级或构建相关公开 hvigor 任务模板。",
        }

    if kind == "project_config":
        return {
            "path": display,
            "kind": kind,
            "module": None,
            "task_template": "<project-level public build task from hvigor tasks>",
            "confidence": "template",
            "requires_task_listing": False,
            "reason": "项目级构建配置变更影响范围可能跨模块，只能给出构建相关任务模板。",
        }

    return {
        "path": display,
        "kind": kind,
        "module": module,
        "task_template": None,
        "confidence": "unknown",
        "requires_task_listing": True,
        "reason": "未识别到可稳定映射的 Harmony 页面、资源或构建配置路径；需先列出公开 hvigor tasks 再选择任务。",
    }


def recommend_tasks_for_paths(repo_arg: str | None, paths: list[str]) -> dict:
    repo_info = resolve_repo_paths(repo_arg)
    repo = Path(repo_info["local_path"])
    recommendations = [recommendation_for_path(repo, path) for path in paths]
    return {
        "repo": repo_info,
        "recommendations": recommendations,
        "needs_list_tasks": any(item["requires_task_listing"] for item in recommendations),
        "list_tasks_hint": "Run `hvigor tasks` or this skill's list-tasks flow before treating templates as exact task names.",
    }


def print_task_recommendations(result: dict) -> None:
    print("Task recommendations:")
    for item in result.get("recommendations") or []:
        template = item.get("task_template") or "LIST TASKS FIRST"
        module = item.get("module") or "project"
        print(f"- {item['path']}: {template}")
        print(f"  module: {module}; kind: {item['kind']}; confidence: {item['confidence']}")
        print(f"  reason: {item['reason']}")
    if result.get("needs_list_tasks"):
        print(result["list_tasks_hint"])


def extract_public_tasks(tasks_output: str) -> list[str]:
    tasks = []
    seen = set()
    for line in strip_ansi(tasks_output).splitlines():
        match = TASK_LINE_RE.match(line)
        if not match:
            continue
        task = match.group(1)
        if task in seen:
            continue
        seen.add(task)
        tasks.append(task)
    return tasks


def select_build_task(public_tasks: list[str], recommendations: dict | None = None) -> tuple[str | None, str]:
    task_set = set(public_tasks)
    if recommendations:
        for item in recommendations.get("recommendations") or []:
            template = item.get("task_template")
            if template and template in task_set and not template.startswith("<"):
                return template, f"selected path recommendation for {item.get('path')}"

    for preferred in BUILD_TASK_PREFERENCE:
        if preferred in task_set:
            return preferred, "selected preferred public build task from hvigor tasks"
    return None, "no public build task matched known build task names"


def build_selection_failure(
    message: str,
    *,
    exit_code: int = 2,
    timed_out: bool = False,
    duration_seconds: float | None = None,
    phase: str | None = None,
    task: str | None = None,
) -> dict:
    result = {
        "success": False,
        "exit_code": exit_code,
        "output": message,
        "timed_out": timed_out,
    }
    if duration_seconds is not None:
        result["duration_seconds"] = duration_seconds
    if phase:
        result["phase"] = phase
    if task:
        result["task"] = task
    return result


def annotate_hvigor_outcome(outcome: dict, *, phase: str, task: str) -> dict:
    annotated = dict(outcome)
    annotated.setdefault("phase", phase)
    annotated.setdefault("task", task)
    return annotated


def remaining_timeout_seconds(started_at: float, timeout_seconds: int) -> int:
    remaining = timeout_seconds - (time.monotonic() - started_at)
    if remaining <= 0:
        return 0
    return max(1, math.ceil(remaining))


def build_deadline_failure(started_at: float, timeout_seconds: int, phase: str, task: str | None = None) -> dict:
    duration_seconds = round(time.monotonic() - started_at, 3)
    target = f" before {phase}"
    if task:
        target += f" `{task}`"
    return build_selection_failure(
        f"Build flow timed out{target} after {timeout_seconds} seconds.",
        exit_code=124,
        timed_out=True,
        duration_seconds=duration_seconds,
        phase=phase,
        task=task,
    )


def emit_build_progress(progress, phase: str, message: str) -> None:
    if progress:
        progress(f"[harmony-build] {phase}: {message}")


def compact_build_result_for_agent(result: dict) -> dict:
    compact = dict(result)
    verification = dict(compact.get("verification") or {})
    if verification.get("success"):
        verification["output"] = ""
    compact["verification"] = verification

    task_list = compact.get("task_list")
    if isinstance(task_list, dict) and task_list.get("success"):
        compact_task_list = dict(task_list)
        compact_task_list["output"] = ""
        compact["task_list"] = compact_task_list
    return compact


def validate_hvigor_task(task: str) -> str | None:
    if not task or not task.strip():
        return "hvigor task must not be empty"
    if task.strip().startswith("-"):
        return "hvigor task must not start with '-' because option-like values are not public task names"
    if any(char in task for char in "\r\n\x00"):
        return "hvigor task must not contain control characters"
    if "@" in task:
        return (
            "hvigor task must be a public task name, not an internal .hvigor task key "
            "such as ':entry:default@CompileArkTS'"
        )
    return None


def should_save_ready_baseline_for_task(task: str | None) -> bool:
    return (task or "").strip() != "tasks"


def read_file_tail(path: Path, *, max_lines: int = HVIGOR_OUTPUT_TAIL_LINES, max_bytes: int = HVIGOR_OUTPUT_TAIL_BYTES) -> str:
    if not path.exists():
        return ""

    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        start = max(0, size - max_bytes)
        handle.seek(start)
        data = handle.read()

    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if start > 0 and lines:
        lines = lines[1:]
    lines = [line for line in lines if line.strip()]
    return "\n".join(lines[-max_lines:])


def read_file_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def clean_hvigor_output(text: str) -> str:
    lines = []
    for line in strip_ansi(text).splitlines():
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def terminate_process_tree(process: subprocess.Popen) -> str | None:
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                return f"taskkill.exe exited with code {result.returncode}"
        else:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
            return None
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
                return "hvigor process tree required SIGKILL after SIGTERM timeout."
            process.kill()
            process.wait(timeout=5)
            return "hvigor process required kill after taskkill timeout."
        return None
    except ProcessLookupError:
        return None
    except Exception as error:
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=5)
        except Exception:
            pass
        return f"failed to terminate hvigor process tree: {error}"


def run_hvigor_task(
    repo_local: str,
    sdk_home: str,
    hvigor_path: str,
    task: str,
    timeout_seconds: int = HVIGOR_TASK_TIMEOUT_SECONDS,
    *,
    node_home: str | None = None,
    java_home: str | None = None,
    output_mode: str = "tail",
) -> dict:
    if output_mode not in {"tail", "full", "full-on-success"}:
        raise ValueError("output_mode must be one of: tail, full, full-on-success")

    task_error = validate_hvigor_task(task)
    if task_error:
        return {
            "success": False,
            "exit_code": 2,
            "output": task_error,
            "timed_out": False,
        }

    hvigor = Path(hvigor_path)
    if not is_executable_file(hvigor):
        return {
            "success": False,
            "exit_code": 126,
            "output": hvigor_not_executable_message(hvigor_path, repo_local),
            "timed_out": False,
        }

    repo = Path(repo_local)
    env = os.environ.copy()
    env["DEVECO_SDK_HOME"] = sdk_home
    env.setdefault("HOS_SDK_HOME", sdk_home)
    env.setdefault("OHOS_SDK_HOME", sdk_home)
    if node_home:
        env["NODE_HOME"] = node_home
        env["PATH"] = str(Path(node_home) / "bin") + os.pathsep + env.get("PATH", "")
    if java_home:
        env["JAVA_HOME"] = java_home

    log_path = None
    timed_out = False
    cleanup_error = None
    started_at = time.monotonic()
    exit_code = 1
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", errors="replace", delete=False) as log_file:
            log_path = Path(log_file.name)
            popen_kwargs = {
                "cwd": repo,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "env": env,
            }
            if os.name != "nt":
                popen_kwargs["start_new_session"] = True
            process = subprocess.Popen([str(hvigor), task], **popen_kwargs)
            try:
                exit_code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                exit_code = 124
                log_file.flush()
                cleanup_error = terminate_process_tree(process)

            log_file.flush()
        read_full_output = output_mode == "full" or (output_mode == "full-on-success" and exit_code == 0 and not timed_out)
        if not log_path:
            raw_output = ""
        elif read_full_output:
            raw_output = read_file_text(log_path)
        else:
            raw_output = read_file_tail(log_path)
        output = clean_hvigor_output(raw_output).strip()
    except OSError as error:
        return {
            "success": False,
            "exit_code": getattr(error, "errno", 1) or 1,
            "output": str(error),
            "timed_out": False,
            "duration_seconds": round(time.monotonic() - started_at, 3),
        }
    finally:
        if log_path:
            try:
                log_path.unlink()
            except OSError:
                pass

    if timed_out:
        timeout_message = f"hvigor task timed out after {timeout_seconds} seconds."
        output = "\n".join(part for part in [output, timeout_message, cleanup_error] if part)

    return {
        "success": exit_code == 0,
        "exit_code": exit_code,
        "output": output,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started_at, 3),
    }


def summarize_output(text: str, max_lines: int = 8) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[-max_lines:])


def detect_environment_for_repo(
    repo_info: dict,
    *,
    preflight: bool,
    timeout_seconds: int = HVIGOR_PREFLIGHT_TIMEOUT_SECONDS,
    progress=None,
) -> dict:
    repo = Path(repo_info["local_path"])
    project_markers = detect_project_markers(repo)
    runtime_os = read_project_runtime_os(repo)
    sdk_family = sdk_family_from_runtime_os(runtime_os)
    node_home, node_path, node_candidates = resolve_node()
    java_home, java_path, java_candidates = resolve_java()
    sdk_home, sdk_candidates = resolve_sdk_root(repo)
    hvigor_path, hvigor_candidates, hvigor_kind = resolve_hvigor_path(repo)
    ohpm_path, ohpm_candidates = resolve_optional_tool("ohpm")
    hdc_path, hdc_candidates = resolve_hdc_path(sdk_home)
    deveco_apps = candidate_deveco_apps()

    static_ready = bool(
        repo_info["local_exists"]
        and project_markers
        and node_path
        and sdk_home
        and hvigor_path
    )
    preflight_result = None
    ready = static_ready
    if preflight and static_ready:
        if progress:
            progress(f"[harmony-build] preflight: running `hvigor tasks` with timeout {timeout_seconds}s")
        preflight_result = run_hvigor_task(
            repo_info["local_path"],
            sdk_home,
            hvigor_path,
            "tasks",
            timeout_seconds=timeout_seconds,
            node_home=node_home,
            java_home=java_home,
        )
        ready = preflight_result["success"]

    blockers = []
    blocker_details = {}
    if not repo_info["local_exists"]:
        blockers.append("repo_missing")
    if not project_markers:
        blockers.append("harmony_project_markers_missing")
    if not node_path:
        blockers.append("node_missing")
    if not sdk_home:
        blockers.append("sdk_missing")
        if sdk_family == "harmonyos" and sdk_candidates:
            blocker_details["sdk_missing"] = (
                "Project runtimeOS is HarmonyOS; select a DevEco HarmonyOS SDK root containing "
                "both hms and openharmony components, not only an OpenHarmony API SDK directory."
            )
    if not hvigor_path:
        blockers.append("hvigor_missing_or_not_executable")
        hint = hvigorw_permission_hint(repo)
        if hint:
            blocker_details["hvigor_missing_or_not_executable"] = hint
    if preflight and preflight_result and not preflight_result["success"]:
        blockers.append("hvigor_preflight_failed")

    return {
        "version": CACHE_SCHEMA_VERSION,
        "ready": ready,
        "runtime": {
            "host": RUNTIME,
            "platform": platform.platform(),
        },
        "repo": repo_info,
        "project": {
            "markers": project_markers,
            "is_harmony_project": bool(project_markers),
            "runtime_os": runtime_os,
        },
        "resolved": {
            "node_home": node_home,
            "node_path": node_path,
            "java_home": java_home,
            "java_path": java_path,
            "sdk_home": sdk_home,
            "hvigor_path": hvigor_path,
            "hvigor_kind": hvigor_kind,
            "ohpm_path": ohpm_path,
            "hdc_path": hdc_path,
            "deveco_app": deveco_apps[0] if deveco_apps else None,
        },
        "candidates": {
            "node_path": node_candidates,
            "java_path": java_candidates,
            "sdk_home": sdk_candidates,
            "hvigor_path": hvigor_candidates,
            "ohpm_path": ohpm_candidates,
            "hdc_path": hdc_candidates,
            "deveco_app": deveco_apps,
        },
        "preflight": preflight_result,
        "blockers": blockers,
        "blocker_details": blocker_details,
    }


def detect_environment(
    repo_arg: str | None,
    *,
    preflight: bool,
    timeout_seconds: int = HVIGOR_PREFLIGHT_TIMEOUT_SECONDS,
) -> dict:
    return detect_environment_for_repo(resolve_repo_paths(repo_arg), preflight=preflight, timeout_seconds=timeout_seconds)


def resolve_detection(
    repo_arg: str | None,
    *,
    preflight: bool,
    refresh: bool,
    allow_cache: bool,
    timeout_seconds: int = HVIGOR_PREFLIGHT_TIMEOUT_SECONDS,
    progress=None,
) -> dict:
    repo_info = resolve_repo_paths(repo_arg)
    cache_path = cache_file_for_repo(repo_info)

    if allow_cache and preflight and not refresh:
        cached_result, _cache_meta = load_cached_detection(repo_info)
        if cached_result:
            return cached_result

    result = detect_environment_for_repo(
        repo_info,
        preflight=preflight,
        timeout_seconds=timeout_seconds,
        progress=progress,
    )
    if preflight and result["ready"]:
        result["cache"] = save_cached_detection(result)
    else:
        result["cache"] = build_cache_metadata(cache_path, "fresh", saved=False)
    return result


def resolve_verification_detection(repo_arg: str | None, *, refresh: bool) -> dict:
    repo_info = resolve_repo_paths(repo_arg)
    cache_path = cache_file_for_repo(repo_info)
    if not refresh:
        cached_result, _cache_meta = load_cached_detection(repo_info)
        if cached_result:
            return cached_result

    result = detect_environment_for_repo(repo_info, preflight=False)
    result["cache"] = build_cache_metadata(cache_path, "fresh", saved=False)
    return result


def print_detection(result: dict) -> None:
    repo = result["repo"]
    resolved = result["resolved"]
    cache = result.get("cache") or {}
    project = result.get("project") or {}
    preflight = result.get("preflight") or {}
    blocker_details = result.get("blocker_details") or {}

    print(f"Runtime host: {result['runtime']['host']}")
    print(f"Repo input: {repo['input']}")
    print(f"Repo local path: {repo['local_path']}")
    print(f"Repo local exists: {'yes' if repo['local_exists'] else 'no'}")
    print(f"Harmony project markers: {', '.join(project.get('markers') or []) or 'NOT FOUND'}")
    print(f"Project runtimeOS: {project.get('runtime_os') or 'UNKNOWN'}")
    print(f"Node: {resolved['node_path'] or 'NOT FOUND'}")
    print(f"JAVA_HOME: {resolved['java_home'] or 'NOT FOUND'}")
    print(f"Java: {resolved['java_path'] or 'NOT FOUND'}")
    print(f"Harmony SDK: {resolved['sdk_home'] or 'NOT FOUND'}")
    print(f"hvigor: {resolved['hvigor_path'] or 'NOT FOUND'}")
    print(f"ohpm: {resolved['ohpm_path'] or 'NOT FOUND'}")
    print(f"hdc: {resolved['hdc_path'] or 'NOT FOUND'}")
    print(f"DevEco Studio: {resolved['deveco_app'] or 'NOT FOUND'}")
    if preflight:
        print(f"Preflight task: tasks")
        print(f"Preflight status: {'OK' if preflight.get('success') else 'FAIL'}")
        if preflight.get("output"):
            print("Preflight output:")
            print(summarize_output(preflight["output"]))
    if result.get("blockers"):
        print(f"Blockers: {', '.join(result['blockers'])}")
        for blocker in result["blockers"]:
            detail = blocker_details.get(blocker)
            if detail:
                print(f"  - {detail}")
    if cache:
        print(f"Detection source: {cache['source']}")
        print(f"Environment cache saved: {'yes' if cache.get('saved') else 'no'}")
        if cache.get("path"):
            print(f"Environment cache path: {cache['path']}")
        if cache.get("saved_at"):
            print(f"Environment cache time: {cache['saved_at']}")
        if cache.get("invalid_reason"):
            print(f"Environment cache refresh reason: {cache['invalid_reason']}")
    print(f"Environment ready: {'yes' if result['ready'] else 'no'}")


def sh_literal(value: str) -> str:
    return shlex.quote(value)


def print_env_snippet(result: dict) -> None:
    repo = result["repo"]
    resolved = result["resolved"]
    sdk_home = resolved.get("sdk_home")
    if not repo.get("local_path") or not sdk_home:
        raise RuntimeError("Cannot print env snippet before resolving repo path and Harmony SDK.")

    print(f"export DEVECO_SDK_HOME={sh_literal(sdk_home)}")
    print('export HOS_SDK_HOME="${HOS_SDK_HOME:-$DEVECO_SDK_HOME}"')
    print('export OHOS_SDK_HOME="${OHOS_SDK_HOME:-$DEVECO_SDK_HOME}"')
    if resolved.get("node_home"):
        print(f"export NODE_HOME={sh_literal(resolved['node_home'])}")
        print('export PATH="$NODE_HOME/bin:$PATH"')
    if resolved.get("java_home"):
        print(f"export JAVA_HOME={sh_literal(resolved['java_home'])}")
    print(f"cd {sh_literal(repo['local_path'])}")


def verify_task(
    result: dict,
    task: str,
    timeout_seconds: int = HVIGOR_TASK_TIMEOUT_SECONDS,
    *,
    full_output: bool = False,
) -> dict:
    repo = result["repo"]
    resolved = result["resolved"]
    if not result["ready"]:
        return {
            "success": False,
            "exit_code": 1,
            "output": "Environment is not ready for macOS Harmony hvigor verification.",
            "timed_out": False,
        }
    return run_hvigor_task(
        repo["local_path"],
        resolved["sdk_home"],
        resolved["hvigor_path"],
        task,
        timeout_seconds,
        node_home=resolved.get("node_home"),
        java_home=resolved.get("java_home"),
        output_mode="full-on-success" if full_output else "tail",
    )


def build_project(
    repo_arg: str | None,
    *,
    paths: list[str] | None = None,
    task: str | None = None,
    timeout_seconds: int = HVIGOR_TASK_TIMEOUT_SECONDS,
    list_timeout_seconds: int = HVIGOR_TASK_LIST_TIMEOUT_SECONDS,
    refresh: bool = False,
    progress=None,
) -> dict:
    started_at = time.monotonic()
    paths = paths or []
    emit_build_progress(progress, "detect", "resolving Harmony build environment")
    result = resolve_verification_detection(repo_arg, refresh=refresh)
    recommendations = recommend_tasks_for_paths(repo_arg, paths) if paths else None
    task_list_outcome = None
    public_tasks: list[str] = []
    selected_task = task
    selection_reason = "explicit --task"
    refreshed_after_failure = False

    if not selected_task:
        remaining = remaining_timeout_seconds(started_at, timeout_seconds)
        if remaining <= 0:
            verification = build_deadline_failure(started_at, timeout_seconds, "list-tasks", "tasks")
            return compact_build_result_for_agent({
                "detection": result,
                "paths": paths,
                "task_list": None,
                "public_tasks": [],
                "selected_task": None,
                "selection_reason": "build flow timed out before listing public tasks",
                "recommendations": recommendations,
                "verification": verification,
                "refreshed_after_failure": refreshed_after_failure,
                "timeout_seconds": timeout_seconds,
                "list_timeout_seconds": list_timeout_seconds,
                "duration_seconds": verification.get("duration_seconds"),
            })
        task_list_timeout = min(list_timeout_seconds, remaining)
        if result.get("ready"):
            emit_build_progress(progress, "list-tasks", f"running `hvigor tasks` with timeout {task_list_timeout}s")
        else:
            emit_build_progress(progress, "list-tasks", "environment is not ready; skipping `hvigor tasks`")
        task_list_outcome = annotate_hvigor_outcome(
            verify_task(result, "tasks", task_list_timeout, full_output=True),
            phase="list-tasks",
            task="tasks",
        )
        if (
            result.get("cache", {}).get("source") == "cache"
            and not task_list_outcome["success"]
            and looks_like_environment_failure(task_list_outcome["output"])
        ):
            emit_build_progress(progress, "detect", "refreshing environment baseline after cached task listing failed")
            result = resolve_verification_detection(repo_arg, refresh=True)
            remaining = remaining_timeout_seconds(started_at, timeout_seconds)
            if remaining <= 0:
                verification = build_deadline_failure(started_at, timeout_seconds, "list-tasks", "tasks")
                return compact_build_result_for_agent({
                    "detection": result,
                    "paths": paths,
                    "task_list": task_list_outcome,
                    "public_tasks": [],
                    "selected_task": None,
                    "selection_reason": "build flow timed out before retrying public task listing",
                    "recommendations": recommendations,
                    "verification": verification,
                    "refreshed_after_failure": True,
                    "timeout_seconds": timeout_seconds,
                    "list_timeout_seconds": list_timeout_seconds,
                    "duration_seconds": verification.get("duration_seconds"),
                })
            task_list_timeout = min(list_timeout_seconds, remaining)
            if result.get("ready"):
                emit_build_progress(progress, "list-tasks", f"retrying `hvigor tasks` with timeout {task_list_timeout}s")
            else:
                emit_build_progress(progress, "list-tasks", "environment is not ready after refresh; skipping `hvigor tasks`")
            task_list_outcome = annotate_hvigor_outcome(
                verify_task(result, "tasks", task_list_timeout, full_output=True),
                phase="list-tasks",
                task="tasks",
            )
            refreshed_after_failure = True

        if not task_list_outcome["success"]:
            verification = build_selection_failure(
                "Unable to choose a build task because `hvigor tasks` failed.\n"
                + (task_list_outcome.get("output") or ""),
                exit_code=task_list_outcome.get("exit_code", 1),
                timed_out=task_list_outcome.get("timed_out", False),
                duration_seconds=task_list_outcome.get("duration_seconds"),
                phase="list-tasks",
                task="tasks",
            )
            return compact_build_result_for_agent({
                "detection": result,
                "paths": paths,
                "task_list": task_list_outcome,
                "public_tasks": [],
                "selected_task": None,
                "selection_reason": "hvigor tasks failed; cannot choose a build task",
                "recommendations": recommendations,
                "verification": verification,
                "refreshed_after_failure": refreshed_after_failure,
                "timeout_seconds": timeout_seconds,
                "list_timeout_seconds": list_timeout_seconds,
                "duration_seconds": round(time.monotonic() - started_at, 3),
            })

        public_tasks = extract_public_tasks(task_list_outcome.get("output") or "")
        selected_task, selection_reason = select_build_task(public_tasks, recommendations)
        if not selected_task:
            verification = build_selection_failure(
                "Unable to choose a public build task automatically. "
                "Pass --task with a public hvigor task from list-tasks.",
                phase="select-task",
            )
            return compact_build_result_for_agent({
                "detection": result,
                "paths": paths,
                "task_list": task_list_outcome,
                "public_tasks": public_tasks,
                "selected_task": None,
                "selection_reason": selection_reason,
                "recommendations": recommendations,
                "verification": verification,
                "refreshed_after_failure": refreshed_after_failure,
                "timeout_seconds": timeout_seconds,
                "list_timeout_seconds": list_timeout_seconds,
                "duration_seconds": round(time.monotonic() - started_at, 3),
            })

    remaining = remaining_timeout_seconds(started_at, timeout_seconds)
    if remaining <= 0:
        outcome = build_deadline_failure(started_at, timeout_seconds, "build", selected_task)
        return compact_build_result_for_agent({
            "detection": result,
            "paths": paths,
            "task_list": task_list_outcome,
            "public_tasks": public_tasks,
            "selected_task": selected_task,
            "selection_reason": selection_reason,
            "recommendations": recommendations,
            "verification": outcome,
            "refreshed_after_failure": refreshed_after_failure,
            "timeout_seconds": timeout_seconds,
            "list_timeout_seconds": list_timeout_seconds,
            "duration_seconds": outcome.get("duration_seconds"),
        })
    if result.get("ready"):
        emit_build_progress(progress, "build", f"running `{selected_task}` with timeout {remaining}s")
    else:
        emit_build_progress(progress, "build", f"environment is not ready; skipping `{selected_task}`")
    outcome = annotate_hvigor_outcome(
        verify_task(result, selected_task, remaining),
        phase="build",
        task=selected_task,
    )
    if (
        result.get("cache", {}).get("source") == "cache"
        and not outcome["success"]
        and looks_like_environment_failure(outcome["output"])
    ):
        emit_build_progress(progress, "detect", "refreshing environment baseline after cached build failed")
        result = resolve_verification_detection(repo_arg, refresh=True)
        remaining = remaining_timeout_seconds(started_at, timeout_seconds)
        if remaining <= 0:
            outcome = build_deadline_failure(started_at, timeout_seconds, "build", selected_task)
            return compact_build_result_for_agent({
                "detection": result,
                "paths": paths,
                "task_list": task_list_outcome,
                "public_tasks": public_tasks,
                "selected_task": selected_task,
                "selection_reason": selection_reason,
                "recommendations": recommendations,
                "verification": outcome,
                "refreshed_after_failure": True,
                "timeout_seconds": timeout_seconds,
                "list_timeout_seconds": list_timeout_seconds,
                "duration_seconds": outcome.get("duration_seconds"),
            })
        if result.get("ready"):
            emit_build_progress(progress, "build", f"retrying `{selected_task}` with timeout {remaining}s")
        else:
            emit_build_progress(progress, "build", f"environment is not ready after refresh; skipping `{selected_task}`")
        outcome = annotate_hvigor_outcome(
            verify_task(result, selected_task, remaining),
            phase="build",
            task=selected_task,
        )
        refreshed_after_failure = True
    if (
        outcome["success"]
        and should_save_ready_baseline_for_task(selected_task)
        and result.get("cache", {}).get("source") != "cache"
    ):
        result = dict(result)
        result["ready"] = True
        result["preflight"] = {**outcome, "task": selected_task}
        result["cache"] = save_cached_detection(result)

    return compact_build_result_for_agent({
        "detection": result,
        "paths": paths,
        "task_list": task_list_outcome,
        "public_tasks": public_tasks,
        "selected_task": selected_task,
        "selection_reason": selection_reason,
        "recommendations": recommendations,
        "verification": outcome,
        "refreshed_after_failure": refreshed_after_failure,
        "timeout_seconds": timeout_seconds,
        "list_timeout_seconds": list_timeout_seconds,
        "duration_seconds": round(time.monotonic() - started_at, 3),
    })


def print_build_result(result: dict) -> None:
    detection = result.get("detection") or {}
    repo = detection.get("repo") or {}
    resolved = detection.get("resolved") or {}
    verification = result.get("verification") or {}
    success = verification.get("success")
    print("BUILD SUCCESS" if success else "BUILD FAILED")
    print(f"Repo: {repo.get('local_path') or repo.get('input') or 'UNKNOWN'}")
    print(f"Task: {result.get('selected_task') or 'NOT SELECTED'}")
    if resolved.get("sdk_home"):
        print(f"SDK: {resolved['sdk_home']}")
    if verification.get("phase"):
        print(f"Phase: {verification['phase']}")
    print(f"Exit code: {verification.get('exit_code')}")
    duration = result.get("duration_seconds")
    if duration is None:
        duration = verification.get("duration_seconds")
    if duration is not None:
        print(f"Duration: {duration}s")
    if verification.get("timed_out"):
        print("Timed out: yes")
    blockers = detection.get("blockers") or []
    if not detection.get("ready", True) and blockers:
        print(f"Detection blockers: {', '.join(blockers)}")
        blocker_details = detection.get("blocker_details") or {}
        for blocker in blockers:
            detail = blocker_details.get(blocker)
            if detail:
                print(f"  - {detail}")
    output = verification.get("output")
    if output:
        print("Output:")
        print(summarize_output(output, max_lines=24))


def iter_app_identity_files(repo: Path):
    if not repo.exists() or not repo.is_dir():
        return

    preferred = [
        repo / "AppScope" / "app.json5",
        repo / "src" / "main" / "module.json5",
    ]
    seen = set()
    for path in preferred:
        if path.is_file():
            seen.add(path.resolve())
            yield path

    for root_text, dirnames, filenames in os.walk(repo):
        dirnames[:] = [dirname for dirname in dirnames if dirname not in PROJECT_CONFIG_IGNORED_DIRS]
        for filename in ("app.json5", "module.json5"):
            if filename not in filenames:
                continue
            path = Path(root_text) / filename
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield path


def read_project_bundle_name(repo: Path) -> str | None:
    for path in iter_app_identity_files(repo) or []:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = APP_BUNDLE_NAME_RE.search(strip_json5_comments(text))
        if match:
            return match.group(1).strip()
    return None


def split_repeated_csv(values: list[str] | None) -> list[str]:
    parts = []
    for value in values or []:
        for part in value.split(","):
            normalized = part.strip()
            if normalized:
                parts.append(normalized)
    return unique_values(parts)


def validate_hilog_text_value(value: str, label: str) -> str | None:
    if not value or not value.strip():
        return f"{label} must not be empty"
    if any(char in value for char in "\r\n\x00"):
        return f"{label} must not contain control characters"
    return None


def normalize_hilog_level(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().upper()
    if normalized not in HILOG_LEVELS:
        raise ValueError(f"--level must be one of: {', '.join(sorted(HILOG_LEVELS))}")
    return normalized


def validate_hilog_capture_options(
    *,
    app: str | None,
    keywords: list[str],
    regexes: list[str],
    tags: list[str],
    pids: list[str],
    target: str | None,
    log_types: list[str],
    allow_unfiltered: bool,
) -> str | None:
    for label, values in (
        ("--app", [app] if app else []),
        ("--keyword", keywords),
        ("--regex", regexes),
        ("--tag", tags),
        ("--pid", pids),
        ("--target", [target] if target else []),
        ("--type", log_types),
    ):
        for value in values:
            error = validate_hilog_text_value(value, label)
            if error:
                return error

    if not allow_unfiltered and not any([app, keywords, regexes, tags, pids]):
        return (
            "Refusing unfiltered hilog capture. Pass --app, --keyword, --regex, --tag, or --pid; "
            "use --allow-unfiltered only for an explicit full-device capture."
        )

    for pattern in regexes:
        try:
            re.compile(pattern)
        except re.error as error:
            return f"--regex is invalid: {error}"
    return None


def build_hilog_coarse_regex(app: str | None, keywords: list[str], regexes: list[str], ignore_case: bool) -> str | None:
    if ignore_case:
        return None
    if regexes:
        return "|".join(f"(?:{pattern})" for pattern in regexes)
    literals = []
    if app:
        literals.append(app)
    literals.extend(keywords)
    if not literals:
        return None
    return "|".join(re.escape(item) for item in literals)


def build_hilog_command(
    hdc_path: str,
    *,
    target: str | None,
    snapshot: bool,
    buffer_lines: int,
    level: str | None,
    log_types: list[str],
    tags: list[str],
    pids: list[str],
    coarse_regex: str | None,
) -> list[str]:
    command = [hdc_path]
    if target:
        command.extend(["-t", target])
    command.append("hilog")
    if snapshot:
        command.extend(["-x", "-z", str(buffer_lines)])
    if log_types:
        command.extend(["-t", ",".join(log_types)])
    if level:
        command.extend(["-L", level])
    if tags:
        command.extend(["-T", ",".join(tags)])
    if pids:
        command.extend(["-P", ",".join(pids)])
    if coarse_regex:
        command.extend(["-e", coarse_regex])
    return command


def hilog_line_matches(
    line: str,
    *,
    app: str | None,
    keywords: list[str],
    keyword_match: str,
    regex_patterns: list[re.Pattern],
    ignore_case: bool,
) -> bool:
    haystack = line.casefold() if ignore_case else line
    if app:
        needle = app.casefold() if ignore_case else app
        if needle not in haystack:
            return False
    if keywords:
        needles = [keyword.casefold() if ignore_case else keyword for keyword in keywords]
        checks = [needle in haystack for needle in needles]
        if keyword_match == "all":
            if not all(checks):
                return False
        elif not any(checks):
            return False
    if regex_patterns and not any(pattern.search(line) for pattern in regex_patterns):
        return False
    return True


def filter_hilog_output(
    raw_output: str,
    *,
    app: str | None,
    keywords: list[str],
    keyword_match: str,
    regexes: list[str],
    ignore_case: bool,
    max_lines: int,
) -> dict:
    flags = re.IGNORECASE if ignore_case else 0
    regex_patterns = [re.compile(pattern, flags) for pattern in regexes]
    raw_lines = [line for line in strip_ansi(raw_output).splitlines() if line.strip()]
    matched = [
        line
        for line in raw_lines
        if hilog_line_matches(
            line,
            app=app,
            keywords=keywords,
            keyword_match=keyword_match,
            regex_patterns=regex_patterns,
            ignore_case=ignore_case,
        )
    ]
    returned = matched[-max_lines:] if max_lines else matched
    return {
        "raw_lines": len(raw_lines),
        "matched_lines": len(matched),
        "returned_lines": len(returned),
        "truncated": len(returned) < len(matched),
        "output": "\n".join(returned),
    }


def run_hilog_command(command: list[str], *, duration_seconds: int | None, timeout_seconds: int) -> dict:
    started_at = time.monotonic()
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=duration_seconds if duration_seconds else timeout_seconds,
        )
        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "output": combine_process_output(result.stdout, result.stderr),
            "duration_limited": False,
            "stopped_by_limit": False,
            "timed_out": False,
            "duration_seconds": round(time.monotonic() - started_at, 3),
        }
    except subprocess.TimeoutExpired as error:
        output = combine_process_output(error.stdout, error.stderr)
        return {
            "success": True,
            "exit_code": 0,
            "output": output,
            "duration_limited": bool(duration_seconds),
            "stopped_by_limit": True,
            "timed_out": False,
            "duration_seconds": round(time.monotonic() - started_at, 3),
        }
    except OSError as error:
        return {
            "success": False,
            "exit_code": getattr(error, "errno", 1) or 1,
            "output": str(error),
            "duration_limited": False,
            "stopped_by_limit": False,
            "timed_out": False,
            "duration_seconds": round(time.monotonic() - started_at, 3),
        }


def capture_hilog(
    repo_arg: str | None,
    *,
    app: str | None = None,
    keywords: list[str] | None = None,
    regexes: list[str] | None = None,
    tags: list[str] | None = None,
    pids: list[str] | None = None,
    target: str | None = None,
    level: str | None = None,
    log_types: list[str] | None = None,
    buffer_lines: int = HILOG_DEFAULT_BUFFER_LINES,
    max_lines: int = HILOG_DEFAULT_MAX_LINES,
    duration_seconds: int | None = None,
    timeout_seconds: int = HILOG_DEFAULT_TIMEOUT_SECONDS,
    allow_unfiltered: bool = False,
    infer_app: bool = True,
    keyword_match: str = "any",
    ignore_case: bool = False,
) -> dict:
    repo_info = resolve_repo_paths(repo_arg)
    repo = Path(repo_info["local_path"])
    sdk_home, sdk_candidates = resolve_sdk_root(repo)
    hdc_path, hdc_candidates = resolve_hdc_path(sdk_home)
    inferred_app = read_project_bundle_name(repo) if infer_app and repo_info.get("local_exists") else None
    effective_app = app or inferred_app
    keywords = keywords or []
    regexes = regexes or []
    tags = tags or []
    pids = pids or []
    log_types = log_types or []
    level = normalize_hilog_level(level)

    validation_error = validate_hilog_capture_options(
        app=effective_app,
        keywords=keywords,
        regexes=regexes,
        tags=tags,
        pids=pids,
        target=target,
        log_types=log_types,
        allow_unfiltered=allow_unfiltered,
    )
    if validation_error:
        return {
            "success": False,
            "exit_code": 2,
            "repo": repo_info,
            "resolved": {
                "sdk_home": sdk_home,
                "hdc_path": hdc_path,
                "inferred_app": inferred_app,
            },
            "candidates": {
                "sdk_home": sdk_candidates,
                "hdc_path": hdc_candidates,
            },
            "filters": {
                "app": effective_app,
                "keywords": keywords,
                "regexes": regexes,
                "tags": tags,
                "pids": pids,
            },
            "capture": {
                "success": False,
                "exit_code": 2,
                "output": validation_error,
                "matched_lines": 0,
                "returned_lines": 0,
                "truncated": False,
            },
        }

    if not hdc_path:
        return {
            "success": False,
            "exit_code": 1,
            "repo": repo_info,
            "resolved": {
                "sdk_home": sdk_home,
                "hdc_path": None,
                "inferred_app": inferred_app,
            },
            "candidates": {
                "sdk_home": sdk_candidates,
                "hdc_path": hdc_candidates,
            },
            "filters": {
                "app": effective_app,
                "keywords": keywords,
                "regexes": regexes,
                "tags": tags,
                "pids": pids,
            },
            "capture": {
                "success": False,
                "exit_code": 1,
                "output": "hdc executable was not found. Install DevEco Studio or add hdc to PATH.",
                "matched_lines": 0,
                "returned_lines": 0,
                "truncated": False,
            },
        }

    snapshot = duration_seconds is None
    coarse_regex = build_hilog_coarse_regex(effective_app, keywords, regexes, ignore_case)
    command = build_hilog_command(
        hdc_path,
        target=target,
        snapshot=snapshot,
        buffer_lines=buffer_lines,
        level=level,
        log_types=log_types,
        tags=tags,
        pids=pids,
        coarse_regex=coarse_regex,
    )
    hdc_outcome = run_hilog_command(command, duration_seconds=duration_seconds, timeout_seconds=timeout_seconds)
    if hdc_outcome["success"]:
        capture = filter_hilog_output(
            hdc_outcome.get("output") or "",
            app=effective_app,
            keywords=keywords,
            keyword_match=keyword_match,
            regexes=regexes,
            ignore_case=ignore_case,
            max_lines=max_lines,
        )
        capture.update(
            {
                "success": True,
                "exit_code": 0,
                "timed_out": False,
                "duration_limited": hdc_outcome.get("duration_limited", False),
                "stopped_by_limit": hdc_outcome.get("stopped_by_limit", False),
                "duration_seconds": hdc_outcome.get("duration_seconds"),
            }
        )
    else:
        diagnostic = clean_hvigor_output(hdc_outcome.get("output") or "")
        capture = {
            "success": False,
            "exit_code": hdc_outcome.get("exit_code", 1),
            "timed_out": hdc_outcome.get("timed_out", False),
            "duration_limited": False,
            "stopped_by_limit": hdc_outcome.get("stopped_by_limit", False),
            "duration_seconds": hdc_outcome.get("duration_seconds"),
            "raw_lines": len([line for line in diagnostic.splitlines() if line.strip()]),
            "matched_lines": 0,
            "returned_lines": 0,
            "truncated": False,
            "output": summarize_output(diagnostic, max_lines=24),
        }

    return {
        "success": bool(capture["success"]),
        "exit_code": capture["exit_code"],
        "repo": repo_info,
        "resolved": {
            "sdk_home": sdk_home,
            "hdc_path": hdc_path,
            "inferred_app": inferred_app,
        },
        "candidates": {
            "sdk_home": sdk_candidates,
            "hdc_path": hdc_candidates,
        },
        "mode": "snapshot" if snapshot else "live",
        "target": target,
        "command": command,
        "filters": {
            "app": effective_app,
            "explicit_app": app,
            "inferred_app": inferred_app,
            "keywords": keywords,
            "keyword_match": keyword_match,
            "regexes": regexes,
            "tags": tags,
            "pids": pids,
            "level": level,
            "types": log_types,
            "ignore_case": ignore_case,
            "coarse_regex": coarse_regex,
            "allow_unfiltered": allow_unfiltered,
        },
        "limits": {
            "buffer_lines": buffer_lines if snapshot else None,
            "max_lines": max_lines,
            "duration_seconds": duration_seconds,
            "timeout_seconds": timeout_seconds if snapshot else None,
        },
        "capture": capture,
    }


def print_hilog_capture(result: dict) -> None:
    capture = result.get("capture") or {}
    resolved = result.get("resolved") or {}
    filters = result.get("filters") or {}
    limits = result.get("limits") or {}
    repo = result.get("repo") or {}

    print("HILOG CAPTURE SUCCESS" if capture.get("success") else "HILOG CAPTURE FAILED")
    print(f"Repo: {repo.get('local_path') or repo.get('input') or 'UNKNOWN'}")
    print(f"hdc: {resolved.get('hdc_path') or 'NOT FOUND'}")
    print(f"Mode: {result.get('mode') or 'UNKNOWN'}")
    if result.get("target"):
        print(f"Target: {result['target']}")
    if filters.get("app"):
        source = "inferred" if filters.get("inferred_app") and not filters.get("explicit_app") else "explicit"
        print(f"App: {filters['app']} ({source})")
    if filters.get("keywords"):
        print(f"Keywords: {', '.join(filters['keywords'])} ({filters.get('keyword_match')})")
    if filters.get("regexes"):
        print(f"Regex: {', '.join(filters['regexes'])}")
    if filters.get("tags"):
        print(f"Tags: {', '.join(filters['tags'])}")
    if filters.get("pids"):
        print(f"PIDs: {', '.join(filters['pids'])}")
    if filters.get("level"):
        print(f"Level: {filters['level']}")
    if limits.get("duration_seconds"):
        print(f"Duration limit: {limits['duration_seconds']}s")
    elif limits.get("buffer_lines"):
        print(f"Device buffer tail: {limits['buffer_lines']} lines")
    print(f"Matched lines: {capture.get('matched_lines', 0)}")
    print(f"Returned lines: {capture.get('returned_lines', 0)}")
    print(f"Truncated: {'yes' if capture.get('truncated') else 'no'}")
    if capture.get("duration_limited"):
        print("Stopped by duration: yes")
    elif capture.get("stopped_by_limit"):
        print("Stopped by snapshot timeout: yes")
    if capture.get("timed_out"):
        print("Timed out: yes")
    if capture.get("output"):
        print("Output:")
        print(capture["output"])


def looks_like_environment_failure(output: str) -> bool:
    lowered = output.lower()
    return any(marker.lower() in lowered for marker in ENV_FAILURE_MARKERS)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def hvigor_task_arg(value: str) -> str:
    task_error = validate_hvigor_task(value)
    if task_error:
        raise argparse.ArgumentTypeError(task_error)
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detect and verify macOS HarmonyOS/OpenHarmony hvigor environments.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect_parser = subparsers.add_parser("detect", help="Detect local macOS Harmony development environment.")
    detect_parser.add_argument("--repo", help="Harmony project root. Defaults to current working directory.")
    detect_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    detect_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cached ready baselines and rerun detection.",
    )
    detect_parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip 'hvigor tasks' preflight and only perform static environment detection.",
    )
    detect_parser.add_argument(
        "--skip-sdk-probe",
        action="store_true",
        dest="skip_preflight",
        help=argparse.SUPPRESS,
    )
    detect_parser.add_argument(
        "--timeout-seconds",
        type=positive_int,
        default=HVIGOR_PREFLIGHT_TIMEOUT_SECONDS,
        help=f"Hard timeout for the detect preflight `hvigor tasks`. Defaults to {HVIGOR_PREFLIGHT_TIMEOUT_SECONDS}.",
    )
    detect_parser.add_argument(
        "--doctor",
        action="store_true",
        help="Include version probes, macOS java_home -V summary, SDK components, and DevEco candidates.",
    )
    detect_parser.add_argument(
        "--recommend-task",
        action="store_true",
        help="Print hvigor task templates for changed paths without running hvigor.",
    )
    detect_parser.add_argument(
        "--paths",
        nargs="+",
        help="Changed paths used with --recommend-task.",
    )

    doctor_parser = subparsers.add_parser("doctor", help="Collect diagnostic details without running hvigor.")
    doctor_parser.add_argument("--repo", help="Harmony project root. Defaults to current working directory.")
    doctor_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")

    recommend_parser = subparsers.add_parser("recommend-task", help="Recommend minimal hvigor task templates for changed paths.")
    recommend_parser.add_argument("--repo", help="Harmony project root. Defaults to current working directory.")
    recommend_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    recommend_parser.add_argument("paths", nargs="+", help="Changed files or directories.")

    list_tasks_parser = subparsers.add_parser("list-tasks", help="Run the public hvigor tasks listing flow.")
    list_tasks_parser.add_argument("--repo", help="Harmony project root. Defaults to current working directory.")
    list_tasks_parser.add_argument(
        "--timeout-seconds",
        type=positive_int,
        default=HVIGOR_TASK_LIST_TIMEOUT_SECONDS,
        help=f"Hard timeout for the hvigor process wrapper. Defaults to {HVIGOR_TASK_LIST_TIMEOUT_SECONDS}.",
    )
    list_tasks_parser.add_argument("--json", action="store_true", help="Print detection result and tasks outcome as JSON.")
    list_tasks_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cached ready baselines and rerun detection before listing tasks.",
    )

    verify_parser = subparsers.add_parser("verify", help="Run a public hvigor task with the detected macOS environment.")
    verify_parser.add_argument("--repo", help="Harmony project root. Defaults to current working directory.")
    verify_parser.add_argument("--task", required=True, type=hvigor_task_arg, help="Required public hvigor task to run.")
    verify_parser.add_argument(
        "--timeout-seconds",
        type=positive_int,
        default=HVIGOR_TASK_TIMEOUT_SECONDS,
        help=f"Hard timeout for the hvigor process wrapper. Defaults to {HVIGOR_TASK_TIMEOUT_SECONDS}.",
    )
    verify_parser.add_argument("--json", action="store_true", help="Print detection result and verification outcome as JSON.")
    verify_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cached ready baselines and rerun detection before verification.",
    )

    build_parser_cmd = subparsers.add_parser("build", help="Automatically choose and run a public hvigor build task.")
    build_parser_cmd.add_argument("--repo", help="Harmony project root. Defaults to current working directory.")
    build_parser_cmd.add_argument(
        "--task",
        type=hvigor_task_arg,
        help="Explicit public hvigor task to run. Overrides automatic selection.",
    )
    build_parser_cmd.add_argument("--paths", nargs="*", default=[], help="Changed paths used to prefer a smaller module build task.")
    build_parser_cmd.add_argument(
        "--timeout-seconds",
        type=positive_int,
        default=HVIGOR_TASK_TIMEOUT_SECONDS,
        help=f"Total hvigor wait budget for the build flow. Defaults to {HVIGOR_TASK_TIMEOUT_SECONDS}.",
    )
    build_parser_cmd.add_argument(
        "--list-timeout-seconds",
        type=positive_int,
        default=HVIGOR_TASK_LIST_TIMEOUT_SECONDS,
        help=f"Hard timeout for automatic `hvigor tasks` discovery. Defaults to {HVIGOR_TASK_LIST_TIMEOUT_SECONDS}.",
    )
    build_parser_cmd.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    build_parser_cmd.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cached ready baselines and rerun detection before building.",
    )

    logs_parser = subparsers.add_parser("capture-logs", help="Capture bounded device HiLog output through hdc.")
    logs_parser.add_argument("--repo", help="Harmony project root. Defaults to current working directory.")
    logs_parser.add_argument(
        "--app",
        help="Application bundle/process text that must appear in returned log lines. Defaults to inferred bundleName when available.",
    )
    logs_parser.add_argument(
        "--no-infer-app",
        action="store_true",
        help="Do not infer bundleName from the project when --app is omitted.",
    )
    logs_parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        help="Keyword that must appear in returned log lines. Repeat to pass multiple keywords.",
    )
    logs_parser.add_argument(
        "--match",
        choices=("any", "all"),
        default="any",
        help="Keyword matching mode when multiple --keyword values are provided. Defaults to any.",
    )
    logs_parser.add_argument(
        "--regex",
        action="append",
        default=[],
        help="Regular expression used for hdc coarse filtering and Python post-filtering. Repeatable.",
    )
    logs_parser.add_argument("--tag", action="append", default=[], help="HiLog tag filter. Repeatable or comma-separated.")
    logs_parser.add_argument("--pid", action="append", default=[], help="HiLog PID filter. Repeatable or comma-separated.")
    logs_parser.add_argument("--target", help="hdc target id used with `hdc -t <target>` when multiple devices are connected.")
    logs_parser.add_argument("--level", help="HiLog level filter: DEBUG, INFO, WARN, ERROR, FATAL, D, I, W, E, or F.")
    logs_parser.add_argument("--type", action="append", default=[], help="HiLog type filter such as app, core, init, or kmsg.")
    logs_parser.add_argument(
        "--duration-seconds",
        type=positive_int,
        help="Capture live logs for this many seconds. Omit to read a bounded device buffer snapshot.",
    )
    logs_parser.add_argument(
        "--buffer-lines",
        type=positive_int,
        default=HILOG_DEFAULT_BUFFER_LINES,
        help=f"Device buffer tail lines for snapshot mode. Defaults to {HILOG_DEFAULT_BUFFER_LINES}.",
    )
    logs_parser.add_argument(
        "--max-lines",
        type=positive_int,
        default=HILOG_DEFAULT_MAX_LINES,
        help=f"Maximum returned matching lines. Defaults to {HILOG_DEFAULT_MAX_LINES}.",
    )
    logs_parser.add_argument(
        "--timeout-seconds",
        type=positive_int,
        default=HILOG_DEFAULT_TIMEOUT_SECONDS,
        help=f"Hard timeout for snapshot mode. Defaults to {HILOG_DEFAULT_TIMEOUT_SECONDS}.",
    )
    logs_parser.add_argument("--ignore-case", action="store_true", help="Post-filter app, keyword, and regex matches case-insensitively.")
    logs_parser.add_argument(
        "--allow-unfiltered",
        action="store_true",
        help="Allow full-device capture without app, keyword, regex, tag, or pid filters.",
    )
    logs_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")

    env_parser = subparsers.add_parser("print-env", help="Print a zsh/bash environment bootstrap snippet.")
    env_parser.add_argument("--repo", help="Harmony project root. Defaults to current working directory.")
    env_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cached ready baselines and rerun detection before printing env.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "detect":
            preflight = not args.skip_preflight
            progress = None
            if not args.json:
                progress = lambda message: print(message, file=sys.stderr, flush=True)
            result = resolve_detection(
                args.repo,
                preflight=preflight,
                refresh=args.refresh,
                allow_cache=preflight,
                timeout_seconds=args.timeout_seconds,
                progress=progress,
            )
            doctor_report = build_doctor_report_from_detection(result) if args.doctor else None
            task_recommendations = None
            if args.recommend_task:
                if not args.paths:
                    raise RuntimeError("--recommend-task requires --paths")
                task_recommendations = recommend_tasks_for_paths(args.repo, args.paths)
            if args.json:
                payload = dict(result)
                if doctor_report is not None:
                    payload["doctor"] = doctor_report
                if task_recommendations is not None:
                    payload["task_recommendations"] = task_recommendations
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print_detection(result)
                if doctor_report is not None:
                    print_doctor_report(doctor_report)
                if task_recommendations is not None:
                    print_task_recommendations(task_recommendations)
            return 0 if result["ready"] else 1

        if args.command == "doctor":
            report = build_doctor_report(args.repo)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print_detection(report["detection"])
                print_doctor_report(report["doctor"])
            return 0

        if args.command == "recommend-task":
            result = recommend_tasks_for_paths(args.repo, args.paths)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print_task_recommendations(result)
            return 0 if not result["needs_list_tasks"] else 1

        if args.command == "list-tasks":
            result = resolve_verification_detection(
                args.repo,
                refresh=args.refresh,
            )
            if not args.json:
                if result["ready"]:
                    print(f"[harmony-build] list-tasks: running `hvigor tasks` with timeout {args.timeout_seconds}s", file=sys.stderr, flush=True)
                else:
                    print("[harmony-build] list-tasks: environment is not ready; skipping `hvigor tasks`", file=sys.stderr, flush=True)
            outcome = verify_task(result, "tasks", args.timeout_seconds, full_output=True)
            if args.json:
                print(
                    json.dumps(
                        {
                            "detection": result,
                            "task": "tasks",
                            "verification": outcome,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                if not result["ready"]:
                    print_detection(result)
                if outcome["output"]:
                    print(outcome["output"])
            return outcome["exit_code"]

        if args.command == "verify":
            result = resolve_verification_detection(
                args.repo,
                refresh=args.refresh,
            )
            if not args.json:
                if result["ready"]:
                    print(f"[harmony-build] verify: running `{args.task}` with timeout {args.timeout_seconds}s", file=sys.stderr, flush=True)
                else:
                    print(f"[harmony-build] verify: environment is not ready; skipping `{args.task}`", file=sys.stderr, flush=True)
            outcome = verify_task(result, args.task, args.timeout_seconds)
            refreshed_after_failure = False
            if (
                result.get("cache", {}).get("source") == "cache"
                and not outcome["success"]
                and looks_like_environment_failure(outcome["output"])
            ):
                result = resolve_verification_detection(
                    args.repo,
                    refresh=True,
                )
                if not args.json:
                    if result["ready"]:
                        print(f"[harmony-build] verify: retrying `{args.task}` after refreshing environment baseline", file=sys.stderr, flush=True)
                    else:
                        print(f"[harmony-build] verify: environment is not ready after refresh; skipping `{args.task}`", file=sys.stderr, flush=True)
                outcome = verify_task(result, args.task, args.timeout_seconds)
                refreshed_after_failure = True
            if (
                outcome["success"]
                and should_save_ready_baseline_for_task(args.task)
                and result.get("cache", {}).get("source") != "cache"
            ):
                result = dict(result)
                result["ready"] = True
                result["preflight"] = {**outcome, "task": args.task}
                result["cache"] = save_cached_detection(result)
            if args.json:
                print(
                    json.dumps(
                        {
                            "detection": result,
                            "task": args.task,
                            "verification": outcome,
                            "refreshed_after_failure": refreshed_after_failure,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                if not result["ready"]:
                    print_detection(result)
                elif refreshed_after_failure:
                    print("Refreshed environment baseline after cached verification hit an environment error.")
                if outcome["output"]:
                    print(outcome["output"])
            return outcome["exit_code"]

        if args.command == "build":
            progress = None
            if not args.json:
                progress = lambda message: print(message, file=sys.stderr, flush=True)
            result = build_project(
                args.repo,
                paths=args.paths,
                task=args.task,
                timeout_seconds=args.timeout_seconds,
                list_timeout_seconds=args.list_timeout_seconds,
                refresh=args.refresh,
                progress=progress,
            )
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print_build_result(result)
            return result["verification"]["exit_code"]

        if args.command == "capture-logs":
            result = capture_hilog(
                args.repo,
                app=args.app,
                keywords=args.keyword,
                regexes=args.regex,
                tags=split_repeated_csv(args.tag),
                pids=split_repeated_csv(args.pid),
                target=args.target,
                level=args.level,
                log_types=split_repeated_csv(args.type),
                buffer_lines=args.buffer_lines,
                max_lines=args.max_lines,
                duration_seconds=args.duration_seconds,
                timeout_seconds=args.timeout_seconds,
                allow_unfiltered=args.allow_unfiltered,
                infer_app=not args.no_infer_app,
                keyword_match=args.match,
                ignore_case=args.ignore_case,
            )
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print_hilog_capture(result)
            return result["exit_code"]

        if args.command == "print-env":
            result = resolve_detection(
                args.repo,
                preflight=True,
                refresh=args.refresh,
                allow_cache=True,
            )
            print_env_snippet(result)
            return 0

        parser.print_help()
        return 1
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
