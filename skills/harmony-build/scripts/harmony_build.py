#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

DEFAULT_HVIGOR = r"C:\Program Files\Huawei\DevEco Studio\tools\hvigor\bin\hvigorw.bat"
DEFAULT_NODE_HOME = r"C:\Program Files\nodejs"
DEFAULT_DEVECO_SDK_HOME = r"C:\Program Files\Huawei\DevEco Studio\sdk"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
WSL_MOUNT_RE = re.compile(r"^/mnt/([a-zA-Z])(?:/(.*))?$")
CACHE_SCHEMA_VERSION = 1
SKILL_RUNTIME_ROOT_ENV = "SKILLS_HUB_RUNTIME_DIR"
SKILL_CACHE_DIR_NAME = "harmony-build"
ENV_FAILURE_MARKERS = (
    "NODE_HOME is not set and no 'node' command could be found in your PATH",
    "Invalid value of 'DEVECO_SDK_HOME' in the system environment path",
    "SDK component missing",
)
HVIGOR_TASK_TIMEOUT_SECONDS = 900
HVIGOR_OUTPUT_TAIL_LINES = 80
HVIGOR_OUTPUT_TAIL_BYTES = 128 * 1024
POWERSHELL_PID_MARKER = "__SKILLS_HUB_POWERSHELL_PID="


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def detect_runtime() -> str:
    if os.name == "nt":
        return "windows"
    release = platform.uname().release.lower()
    if "microsoft" in release or os.environ.get("WSL_DISTRO_NAME"):
        return "wsl"
    return "linux"


RUNTIME = detect_runtime()


def is_windows_path(path_text: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", path_text.strip()))


def is_wsl_mounted_windows_path(path_text: str) -> bool:
    normalized = path_text.replace("\\", "/").strip()
    return bool(WSL_MOUNT_RE.match(normalized))


def normalize_windows_path(path_text: str) -> str:
    value = path_text.strip().replace("/", "\\")
    drive_root = re.match(r"^([A-Za-z]):\\?$", value)
    if drive_root:
        return f"{drive_root.group(1).upper()}:\\"
    value = value.rstrip("\\/")
    return value


def wsl_to_windows_path(path_text: str) -> str:
    normalized = str(path_text).replace("\\", "/")
    if not normalized.startswith("/mnt/"):
        normalized = str(Path(path_text).resolve()).replace("\\", "/")
    match = WSL_MOUNT_RE.match(normalized)
    if not match:
        raise ValueError(f"Path is not on a mounted Windows drive: {path_text}")
    drive = match.group(1).upper()
    remainder = match.group(2) or ""
    if not remainder:
        return f"{drive}:\\"
    return f"{drive}:\\{remainder.replace('/', '\\')}"


def windows_to_wsl_path(path_text: str) -> str:
    value = normalize_windows_path(path_text)
    match = re.match(r"^([A-Za-z]):\\?(.*)$", value)
    if not match:
        raise ValueError(f"Not a Windows path: {path_text}")
    drive = match.group(1).lower()
    remainder = match.group(2)
    if not remainder:
        return f"/mnt/{drive}"
    return f"/mnt/{drive}/{remainder.replace('\\', '/')}"


def resolve_host_path(path_text: str) -> Path | None:
    if not path_text:
        return None
    if is_windows_path(path_text):
        normalized = normalize_windows_path(path_text)
        if RUNTIME == "windows":
            return Path(normalized)
        if RUNTIME == "wsl":
            try:
                return Path(windows_to_wsl_path(normalized))
            except ValueError:
                return None
        return None
    return Path(path_text)


def host_path_exists(path_text: str) -> bool:
    host_path = resolve_host_path(path_text)
    return bool(host_path and host_path.exists())


def host_dir_children(path_text: str) -> list[str]:
    host_path = resolve_host_path(path_text)
    if host_path is None or not host_path.exists() or not host_path.is_dir():
        return []

    children = []
    for child in sorted(host_path.iterdir()):
        if not child.is_dir():
            continue
        if is_windows_path(path_text):
            if RUNTIME == "windows":
                children.append(normalize_windows_path(str(child)))
            elif RUNTIME == "wsl":
                children.append(wsl_to_windows_path(str(child)))
            continue
        children.append(str(child))
    return children


def ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_powershell(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def parse_json_output(result: subprocess.CompletedProcess) -> dict:
    if result.returncode != 0:
        stderr = strip_ansi(result.stderr).strip()
        stdout = strip_ansi(result.stdout).strip()
        raise RuntimeError(stderr or stdout or "PowerShell command failed")
    payload = result.stdout.strip()
    if not payload:
        return {}
    return json.loads(payload)


def ensure_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def unique_values(values):
    seen = set()
    result = []
    for item in values:
        if not item:
            continue
        normalized = item.strip()
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

    if RUNTIME == "windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "skills-hub" / SKILL_CACHE_DIR_NAME


def legacy_cache_root_dir() -> Path | None:
    if os.environ.get(SKILL_RUNTIME_ROOT_ENV):
        return None

    if RUNTIME == "windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "codex" / SKILL_CACHE_DIR_NAME


def repo_identity(repo_info: dict) -> str:
    for candidate in [repo_info.get("windows_path"), repo_info.get("local_path"), repo_info.get("input")]:
        if not candidate:
            continue
        if is_windows_path(candidate):
            return normalize_windows_path(candidate)
        return str(Path(candidate).resolve())
    return "unknown-repo"


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


def is_cached_detection_usable(result: dict | None, repo_info: dict) -> tuple[bool, str | None]:
    if not isinstance(result, dict):
        return False, "invalid_payload"

    cached_repo = result.get("repo") or {}
    resolved = result.get("resolved") or {}
    if repo_identity(cached_repo) != repo_identity(repo_info):
        return False, "repo_mismatch"
    if not result.get("ready"):
        return False, "not_ready"
    if not cached_repo.get("windows_compatible"):
        return False, "repo_not_windows_compatible"

    checks = [
        ("repo_local_path", cached_repo.get("local_path")),
        ("repo_windows_path", cached_repo.get("windows_path")),
        ("node_home", resolved.get("node_home")),
        ("node_path", resolved.get("node_path")),
        ("deveco_sdk_home", resolved.get("deveco_sdk_home")),
        ("hvigorw_path", resolved.get("hvigorw_path")),
    ]
    for label, path_text in checks:
        if not path_text or not host_path_exists(path_text):
            return False, f"missing_{label}"
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


def looks_like_environment_failure(output: str) -> bool:
    return any(marker in output for marker in ENV_FAILURE_MARKERS)


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


def read_file_head(path: Path, *, max_bytes: int = 4096) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        data = handle.read(max_bytes)
    return data.decode("utf-8", errors="replace")


def extract_powershell_pid(text: str) -> int | None:
    match = re.search(rf"^{re.escape(POWERSHELL_PID_MARKER)}(\d+)\s*$", text, re.MULTILINE)
    if not match:
        return None
    return int(match.group(1))


def clean_hvigor_output(text: str) -> str:
    lines = []
    for line in strip_ansi(text).splitlines():
        if line.startswith(POWERSHELL_PID_MARKER):
            continue
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def terminate_process_tree(process: subprocess.Popen, windows_pid: int | None) -> str | None:
    pid = windows_pid or process.pid
    try:
        result = subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return f"taskkill.exe exited with code {result.returncode}"
        process.wait(timeout=10)
        return None
    except Exception as error:
        try:
            process.kill()
        except Exception:
            pass
        return f"failed to terminate hvigor process tree: {error}"


def gather_windows_env() -> dict:
    script = """
$result = [ordered]@{
  userProfile = $env:USERPROFILE
  nodeHomeUser = [Environment]::GetEnvironmentVariable('NODE_HOME', 'User')
  nodeHomeMachine = [Environment]::GetEnvironmentVariable('NODE_HOME', 'Machine')
  devecoSdkHomeUser = [Environment]::GetEnvironmentVariable('DEVECO_SDK_HOME', 'User')
  devecoSdkHomeMachine = [Environment]::GetEnvironmentVariable('DEVECO_SDK_HOME', 'Machine')
  nvmHomeUser = [Environment]::GetEnvironmentVariable('NVM_HOME', 'User')
  nvmHomeMachine = [Environment]::GetEnvironmentVariable('NVM_HOME', 'Machine')
  nvmSymlinkUser = [Environment]::GetEnvironmentVariable('NVM_SYMLINK', 'User')
  nvmSymlinkMachine = [Environment]::GetEnvironmentVariable('NVM_SYMLINK', 'Machine')
  pathUser = [Environment]::GetEnvironmentVariable('Path', 'User')
  pathMachine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
}
$result | ConvertTo-Json -Compress
"""
    return parse_json_output(run_powershell(script))


def gather_lookup_paths() -> dict:
    script = """
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
$result = [ordered]@{
  node = @(where.exe node 2>$null)
  npmCmd = @(where.exe npm.cmd 2>$null)
  hvigorw = @(where.exe hvigorw.bat 2>$null)
}
$result | ConvertTo-Json -Compress
"""
    payload = parse_json_output(run_powershell(script))
    return {
        "node": ensure_list(payload.get("node")),
        "npm_cmd": ensure_list(payload.get("npmCmd")),
        "hvigorw": ensure_list(payload.get("hvigorw")),
    }


def resolve_repo_paths(repo_arg: str | None) -> dict:
    repo_input = repo_arg or os.getcwd()
    repo_windows = None
    repo_wsl = None

    if is_windows_path(repo_input):
        repo_windows = normalize_windows_path(repo_input)
        if RUNTIME == "wsl":
            repo_local = windows_to_wsl_path(repo_windows)
            repo_wsl = repo_local
        else:
            repo_local = str(Path(repo_windows).resolve())
        return {
            "input": repo_input,
            "local_path": repo_local,
            "windows_path": repo_windows,
            "wsl_path": repo_wsl,
            "windows_compatible": True,
            "local_exists": host_path_exists(repo_windows),
        }

    if is_wsl_mounted_windows_path(repo_input):
        repo_wsl = str(Path(repo_input).resolve())
        repo_windows = wsl_to_windows_path(repo_wsl)
        return {
            "input": repo_input,
            "local_path": repo_wsl,
            "windows_path": repo_windows,
            "wsl_path": repo_wsl,
            "windows_compatible": True,
            "local_exists": Path(repo_wsl).exists(),
        }

    repo_local = str(Path(repo_input).resolve())
    windows_compatible = False
    if RUNTIME == "windows":
        repo_windows = normalize_windows_path(repo_local) if is_windows_path(repo_local) else None
        windows_compatible = bool(repo_windows)
    elif is_wsl_mounted_windows_path(repo_local):
        repo_wsl = repo_local
        repo_windows = wsl_to_windows_path(repo_wsl)
        windows_compatible = True
    else:
        repo_wsl = repo_local if RUNTIME == "wsl" else None

    return {
        "input": repo_input,
        "local_path": repo_local,
        "windows_path": repo_windows,
        "wsl_path": repo_wsl,
        "windows_compatible": windows_compatible,
        "local_exists": Path(repo_local).exists(),
    }


def resolve_node_home(env_info: dict, lookup_paths: dict) -> tuple[str | None, str | None, list[str]]:
    candidates = [
        env_info.get("nodeHomeUser"),
        env_info.get("nodeHomeMachine"),
    ]
    for node_path in lookup_paths.get("node", []):
        normalized = normalize_windows_path(node_path)
        if is_windows_path(normalized):
            candidates.append(str(PureWindowsPath(normalized).parent))
    candidates.append(DEFAULT_NODE_HOME)

    node_homes = unique_values(normalize_windows_path(item) for item in candidates if item)
    for node_home in node_homes:
        node_exe = normalize_windows_path(node_home + r"\node.exe")
        if host_path_exists(node_exe):
            return node_home, node_exe, node_homes
    return None, None, node_homes


def resolve_hvigorw_path(lookup_paths: dict) -> tuple[str | None, list[str]]:
    candidates = unique_values([DEFAULT_HVIGOR, *lookup_paths.get("hvigorw", [])])
    for candidate in candidates:
        normalized = normalize_windows_path(candidate)
        if host_path_exists(normalized):
            return normalized, candidates
    return None, candidates


def should_expand_sdk_root(path_text: str) -> bool:
    return PureWindowsPath(normalize_windows_path(path_text)).name.lower() == "sdk"


def candidate_sdk_roots(env_info: dict) -> list[str]:
    user_profile = env_info.get("userProfile") or r"C:\Users\Default"
    candidates = [
        env_info.get("devecoSdkHomeUser"),
        env_info.get("devecoSdkHomeMachine"),
        DEFAULT_DEVECO_SDK_HOME,
        r"C:\Program Files\Huawei\DevEco Studio\sdk\default",
        user_profile + r"\AppData\Local\OpenHarmony\Sdk",
        user_profile + r"\AppData\Local\Huawei\Sdk",
    ]
    normalized = [normalize_windows_path(candidate) for candidate in candidates if candidate]
    expanded = []
    for candidate in unique_values(normalized):
        if not host_path_exists(candidate):
            continue
        expanded.append(candidate)
        if should_expand_sdk_root(candidate):
            expanded.extend(host_dir_children(candidate))
    return unique_values(normalize_windows_path(candidate) for candidate in expanded if candidate)


def run_hvigor_task(
    repo_windows: str,
    node_home: str,
    sdk_home: str,
    hvigorw_path: str,
    task: str,
    timeout_seconds: int = HVIGOR_TASK_TIMEOUT_SECONDS,
) -> dict:
    task_error = validate_hvigor_task(task)
    if task_error:
        return {
            "success": False,
            "exit_code": 2,
            "output": task_error,
        }

    script = f"""
Write-Output "{POWERSHELL_PID_MARKER}$PID"
$env:NODE_HOME = {ps_literal(node_home)}
$env:DEVECO_SDK_HOME = {ps_literal(sdk_home)}
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
Set-Location {ps_literal(repo_windows)}
& {ps_literal(hvigorw_path)} {ps_literal(task)}
exit $LASTEXITCODE
"""
    log_path = None
    timed_out = False
    cleanup_error = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", errors="replace", delete=False) as log_file:
            log_path = Path(log_file.name)
            process = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-Command", script],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            try:
                exit_code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                exit_code = 124
                log_file.flush()
                pid_output = "\n".join([read_file_head(log_path), read_file_tail(log_path)])
                cleanup_error = terminate_process_tree(process, extract_powershell_pid(pid_output))

            log_file.flush()
        output = clean_hvigor_output(read_file_tail(log_path)).strip() if log_path else ""
    finally:
        if log_path:
            try:
                log_path.unlink()
            except OSError:
                pass

    if timed_out:
        timeout_message = f"hvigor task timed out after {timeout_seconds} seconds."
        output = "\n".join(part for part in [output, timeout_message] if part)
        if cleanup_error:
            output = "\n".join([output, cleanup_error])

    return {
        "success": exit_code == 0,
        "exit_code": exit_code,
        "output": output,
    }


def summarize_output(text: str, max_lines: int = 8) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[-max_lines:])


def probe_sdk(repo_windows: str | None, node_home: str | None, hvigorw_path: str | None, sdk_candidates: list[str]) -> tuple[str | None, list[dict]]:
    if not repo_windows or not node_home or not hvigorw_path:
        return None, []
    probes = []
    for candidate in sdk_candidates:
        outcome = run_hvigor_task(repo_windows, node_home, candidate, hvigorw_path, "tasks")
        probes.append(
            {
                "sdk_home": candidate,
                "success": outcome["success"],
                "exit_code": outcome["exit_code"],
                "summary": summarize_output(outcome["output"]),
            }
        )
        if outcome["success"]:
            return candidate, probes
    return None, probes


def detect_nvm_residue(env_info: dict) -> list[dict]:
    user_profile = env_info.get("userProfile") or r"C:\Users\Default"
    candidates = unique_values(
        [
            env_info.get("nvmHomeUser"),
            env_info.get("nvmHomeMachine"),
            env_info.get("nvmSymlinkUser"),
            env_info.get("nvmSymlinkMachine"),
            user_profile + r"\AppData\Local\nvm",
            r"C:\nvm4w",
            r"C:\Program Files\nvm",
        ]
    )
    residues = []
    for candidate in candidates:
        normalized = normalize_windows_path(candidate)
        if host_path_exists(normalized):
            residues.append({"path": normalized, "exists": True})
    return residues


def detect_environment_for_repo(repo_info: dict, probe_sdk_roots: bool) -> dict:
    env_info = gather_windows_env()
    lookup_paths = gather_lookup_paths()
    node_home, node_path, node_candidates = resolve_node_home(env_info, lookup_paths)
    hvigorw_path, hvigor_candidates = resolve_hvigorw_path(lookup_paths)
    sdk_candidates = candidate_sdk_roots(env_info)

    if probe_sdk_roots:
        sdk_home, sdk_probes = probe_sdk(repo_info["windows_path"], node_home, hvigorw_path, sdk_candidates)
    else:
        sdk_home = env_info.get("devecoSdkHomeUser") or env_info.get("devecoSdkHomeMachine")
        sdk_home = normalize_windows_path(sdk_home) if sdk_home else None
        if sdk_home and not host_path_exists(sdk_home):
            sdk_home = None
        sdk_probes = []

    ready = bool(
        repo_info["windows_compatible"]
        and repo_info["windows_path"]
        and repo_info["local_exists"]
        and node_home
        and node_path
        and hvigorw_path
        and sdk_home
    )

    return {
        "ready": ready,
        "runtime": {
            "host": RUNTIME,
        },
        "repo": repo_info,
        "resolved": {
            "node_home": node_home,
            "node_path": node_path,
            "deveco_sdk_home": sdk_home,
            "hvigorw_path": hvigorw_path,
        },
        "candidates": {
            "node_home": node_candidates,
            "deveco_sdk_home": sdk_candidates,
            "hvigorw_path": hvigor_candidates,
        },
        "registry_env": {
            "node_home_user": env_info.get("nodeHomeUser"),
            "node_home_machine": env_info.get("nodeHomeMachine"),
            "deveco_sdk_home_user": env_info.get("devecoSdkHomeUser"),
            "deveco_sdk_home_machine": env_info.get("devecoSdkHomeMachine"),
        },
        "lookups": lookup_paths,
        "sdk_probes": sdk_probes,
        "nvm_residue": detect_nvm_residue(env_info),
    }


def detect_environment(repo_arg: str | None, probe_sdk_roots: bool) -> dict:
    return detect_environment_for_repo(resolve_repo_paths(repo_arg), probe_sdk_roots)


def resolve_detection(
    repo_arg: str | None,
    *,
    probe_sdk_roots: bool,
    refresh: bool,
    allow_cache: bool,
) -> dict:
    repo_info = resolve_repo_paths(repo_arg)
    cache_path = cache_file_for_repo(repo_info)

    if allow_cache and not refresh:
        cached_result, _cache_meta = load_cached_detection(repo_info)
        if cached_result:
            return cached_result

    result = detect_environment_for_repo(repo_info, probe_sdk_roots=probe_sdk_roots)
    if probe_sdk_roots and result["ready"]:
        result["cache"] = save_cached_detection(result)
    else:
        result["cache"] = build_cache_metadata(cache_path, "fresh", saved=False)
    return result


def print_detection(result: dict) -> None:
    repo = result["repo"]
    resolved = result["resolved"]
    cache = result.get("cache") or {}
    print(f"Runtime host: {result['runtime']['host']}")
    print(f"Repo input: {repo['input']}")
    print(f"Repo local path: {repo['local_path']}")
    print(f"Repo local exists: {'yes' if repo['local_exists'] else 'no'}")
    print(f"Repo Windows path: {repo['windows_path'] or 'NOT AVAILABLE'}")
    print(f"Repo WSL path: {repo['wsl_path'] or 'NOT AVAILABLE'}")
    print(f"Windows-compatible repo: {'yes' if repo['windows_compatible'] else 'no'}")
    print(f"NODE_HOME: {resolved['node_home'] or 'NOT FOUND'}")
    print(f"node.exe: {resolved['node_path'] or 'NOT FOUND'}")
    print(f"DEVECO_SDK_HOME: {resolved['deveco_sdk_home'] or 'NOT FOUND'}")
    print(f"hvigorw.bat: {resolved['hvigorw_path'] or 'NOT FOUND'}")
    if cache:
        print(f"Detection source: {cache['source']}")
        print(f"Environment cache saved: {'yes' if cache.get('saved') else 'no'}")
        if cache.get("path"):
            print(f"Environment cache path: {cache['path']}")
        if cache.get("saved_at"):
            print(f"Environment cache time: {cache['saved_at']}")
        if cache.get("invalid_reason"):
            print(f"Environment cache refresh reason: {cache['invalid_reason']}")
    if result["nvm_residue"]:
        print("NVM residue:")
        for residue in result["nvm_residue"]:
            print(f"  - {residue['path']}")
    if result["sdk_probes"]:
        print("SDK probes:")
        for probe in result["sdk_probes"]:
            status = "OK" if probe["success"] else "FAIL"
            print(f"  - [{status}] {probe['sdk_home']}")
    print(f"Environment ready: {'yes' if result['ready'] else 'no'}")


def print_env_snippet(result: dict) -> None:
    repo = result["repo"]
    resolved = result["resolved"]
    if not resolved["node_home"] or not resolved["deveco_sdk_home"] or not repo["windows_path"]:
        raise RuntimeError("Cannot print env snippet before resolving repo path, NODE_HOME, and DEVECO_SDK_HOME")
    print(f"$env:NODE_HOME = {ps_literal(resolved['node_home'])}")
    print(f"$env:DEVECO_SDK_HOME = {ps_literal(resolved['deveco_sdk_home'])}")
    print("$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + `")
    print("  [Environment]::GetEnvironmentVariable('Path', 'User')")
    print(f"Set-Location {ps_literal(repo['windows_path'])}")


def verify_task(result: dict, task: str, timeout_seconds: int = HVIGOR_TASK_TIMEOUT_SECONDS) -> dict:
    repo = result["repo"]
    resolved = result["resolved"]
    if not result["ready"]:
        return {
            "success": False,
            "exit_code": 1,
            "output": "Environment is not ready for Windows-side hvigor verification.",
        }
    return run_hvigor_task(
        repo["windows_path"],
        resolved["node_home"],
        resolved["deveco_sdk_home"],
        resolved["hvigorw_path"],
        task,
        timeout_seconds,
    )


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detect and verify HarmonyOS Windows-side build environments.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect_parser = subparsers.add_parser("detect", help="Detect Windows-side HarmonyOS build environment.")
    detect_parser.add_argument("--repo", help="WSL or Windows repo path. Defaults to current working directory.")
    detect_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    detect_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cached ready baselines and rerun full detection.",
    )
    detect_parser.add_argument(
        "--skip-sdk-probe",
        action="store_true",
        help="Do not probe SDK roots with hvigorw.bat tasks.",
    )

    verify_parser = subparsers.add_parser("verify", help="Run Windows-side hvigor verification.")
    verify_parser.add_argument("--repo", help="WSL or Windows repo path. Defaults to current working directory.")
    verify_parser.add_argument("--task", default="tasks", help="hvigor task to run. Defaults to tasks.")
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
        help="Ignore cached ready baselines and rerun full detection before verification.",
    )

    env_parser = subparsers.add_parser("print-env", help="Print a PowerShell env bootstrap snippet.")
    env_parser.add_argument("--repo", help="WSL or Windows repo path. Defaults to current working directory.")
    env_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cached ready baselines and rerun full detection before printing env.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "detect":
            use_cache = not args.skip_sdk_probe
            result = resolve_detection(
                args.repo,
                probe_sdk_roots=not args.skip_sdk_probe,
                refresh=args.refresh,
                allow_cache=use_cache,
            )
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print_detection(result)
            return 0 if result["ready"] else 1

        if args.command == "verify":
            result = resolve_detection(
                args.repo,
                probe_sdk_roots=True,
                refresh=args.refresh,
                allow_cache=True,
            )
            outcome = verify_task(result, args.task, args.timeout_seconds)
            refreshed_after_failure = False
            if (
                result.get("cache", {}).get("source") == "cache"
                and not outcome["success"]
                and looks_like_environment_failure(outcome["output"])
            ):
                result = resolve_detection(
                    args.repo,
                    probe_sdk_roots=True,
                    refresh=True,
                    allow_cache=False,
                )
                outcome = verify_task(result, args.task, args.timeout_seconds)
                refreshed_after_failure = True
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
                probe_sdk_roots=True,
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
