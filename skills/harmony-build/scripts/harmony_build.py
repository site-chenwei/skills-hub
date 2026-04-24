#!/usr/bin/env python3

import argparse
import hashlib
import json
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
CACHE_SCHEMA_VERSION = 2
SKILL_RUNTIME_ROOT_ENV = "SKILLS_HUB_RUNTIME_DIR"
SKILL_CACHE_DIR_NAME = "harmony-build"
HVIGOR_TASK_TIMEOUT_SECONDS = 900
HVIGOR_OUTPUT_TAIL_LINES = 80
HVIGOR_OUTPUT_TAIL_BYTES = 128 * 1024
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

    checks = [
        ("repo_local_path", cached_repo.get("local_path")),
        ("node_path", resolved.get("node_path")),
        ("sdk_home", resolved.get("sdk_home")),
        ("hvigor_path", resolved.get("hvigor_path")),
    ]
    for label, path_text in checks:
        if not host_path_exists(path_text):
            return False, f"missing_{label}"

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


def java_home_from_path(java_path: str | None) -> str | None:
    if not java_path:
        return os.environ.get("JAVA_HOME")
    path = Path(java_path)
    if path.parent.name == "bin":
        return str(path.parent.parent)
    return os.environ.get("JAVA_HOME")


def resolve_java() -> tuple[str | None, str | None, list[str]]:
    candidates = candidate_java_paths()
    java_path = next((item for item in candidates if is_executable_file(Path(item))), None)
    return java_home_from_path(java_path), java_path, candidates


def looks_like_sdk_root(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    marker_dirs = {"ets", "js", "native", "toolchains", "kits", "api"}
    child_names = {child.name for child in path.iterdir() if child.is_dir()}
    return bool(marker_dirs & child_names)


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
        if looks_like_sdk_root(path):
            expanded.append(str(path))
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_dir() and looks_like_sdk_root(child):
                    expanded.append(str(child.resolve()))
    return unique_values(expanded)


def resolve_sdk_root() -> tuple[str | None, list[str]]:
    candidates = candidate_sdk_roots()
    return (candidates[0] if candidates else None), candidates


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
    for item in candidates:
        path = Path(item)
        if is_executable_file(path):
            kind = "repo-wrapper" if path.parent == repo else "path"
            return item, candidates, kind
    return None, candidates, None


def resolve_optional_tool(command_name: str) -> tuple[str | None, list[str]]:
    candidates = which_all(command_name)
    return (candidates[0] if candidates else None), candidates


def validate_hvigor_task(task: str) -> str | None:
    if not task or not task.strip():
        return "hvigor task must not be empty"
    if any(char in task for char in "\r\n\x00"):
        return "hvigor task must not contain control characters"
    if "@" in task:
        return (
            "hvigor task must be a public task name, not an internal .hvigor task key "
            "such as ':entry:default@CompileArkTS'"
        )
    return None


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
        process.wait(timeout=10)
        return None
    except Exception as error:
        try:
            process.kill()
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
) -> dict:
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
            "output": f"hvigor executable is missing or not executable: {hvigor_path}",
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
        output = clean_hvigor_output(read_file_tail(log_path)).strip() if log_path else ""
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
    timeout_seconds: int = HVIGOR_TASK_TIMEOUT_SECONDS,
) -> dict:
    repo = Path(repo_info["local_path"])
    project_markers = detect_project_markers(repo)
    node_home, node_path, node_candidates = resolve_node()
    java_home, java_path, java_candidates = resolve_java()
    sdk_home, sdk_candidates = resolve_sdk_root()
    hvigor_path, hvigor_candidates, hvigor_kind = resolve_hvigor_path(repo)
    ohpm_path, ohpm_candidates = resolve_optional_tool("ohpm")
    hdc_path, hdc_candidates = resolve_optional_tool("hdc")
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
    if not repo_info["local_exists"]:
        blockers.append("repo_missing")
    if not project_markers:
        blockers.append("harmony_project_markers_missing")
    if not node_path:
        blockers.append("node_missing")
    if not sdk_home:
        blockers.append("sdk_missing")
    if not hvigor_path:
        blockers.append("hvigor_missing_or_not_executable")
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
    }


def detect_environment(repo_arg: str | None, *, preflight: bool) -> dict:
    return detect_environment_for_repo(resolve_repo_paths(repo_arg), preflight=preflight)


def resolve_detection(
    repo_arg: str | None,
    *,
    preflight: bool,
    refresh: bool,
    allow_cache: bool,
    timeout_seconds: int = HVIGOR_TASK_TIMEOUT_SECONDS,
) -> dict:
    repo_info = resolve_repo_paths(repo_arg)
    cache_path = cache_file_for_repo(repo_info)

    if allow_cache and preflight and not refresh:
        cached_result, _cache_meta = load_cached_detection(repo_info)
        if cached_result:
            return cached_result

    result = detect_environment_for_repo(repo_info, preflight=preflight, timeout_seconds=timeout_seconds)
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

    print(f"Runtime host: {result['runtime']['host']}")
    print(f"Repo input: {repo['input']}")
    print(f"Repo local path: {repo['local_path']}")
    print(f"Repo local exists: {'yes' if repo['local_exists'] else 'no'}")
    print(f"Harmony project markers: {', '.join(project.get('markers') or []) or 'NOT FOUND'}")
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


def verify_task(result: dict, task: str, timeout_seconds: int = HVIGOR_TASK_TIMEOUT_SECONDS) -> dict:
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
    )


def looks_like_environment_failure(output: str) -> bool:
    lowered = output.lower()
    return any(marker.lower() in lowered for marker in ENV_FAILURE_MARKERS)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


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

    verify_parser = subparsers.add_parser("verify", help="Run a public hvigor task with the detected macOS environment.")
    verify_parser.add_argument("--repo", help="Harmony project root. Defaults to current working directory.")
    verify_parser.add_argument("--task", default="tasks", help="Public hvigor task to run. Defaults to tasks.")
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
            result = resolve_detection(
                args.repo,
                preflight=preflight,
                refresh=args.refresh,
                allow_cache=preflight,
            )
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print_detection(result)
            return 0 if result["ready"] else 1

        if args.command == "verify":
            result = resolve_verification_detection(
                args.repo,
                refresh=args.refresh,
            )
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
                outcome = verify_task(result, args.task, args.timeout_seconds)
                refreshed_after_failure = True
            if outcome["success"] and result.get("cache", {}).get("source") != "cache":
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
