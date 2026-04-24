import io
import importlib.util
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "harmony_build.py"
SPEC = importlib.util.spec_from_file_location("harmony_build", SCRIPT_PATH)
HARMONY_BUILD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(HARMONY_BUILD)


class HarmonyBuildCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache_root = Path(self.temp_dir.name) / "cache"
        self.repo_local = Path(self.temp_dir.name) / "repo"
        self.repo_local.mkdir()
        self.repo_info = {
            "input": str(self.repo_local),
            "local_path": str(self.repo_local),
            "local_exists": True,
        }
        self.ready_result = {
            "version": HARMONY_BUILD.CACHE_SCHEMA_VERSION,
            "ready": True,
            "runtime": {"host": "macos", "platform": "macOS"},
            "repo": dict(self.repo_info),
            "project": {"markers": ["build-profile.json5"], "is_harmony_project": True},
            "resolved": {
                "node_home": "/opt/homebrew",
                "node_path": "/opt/homebrew/bin/node",
                "java_home": "/Library/Java/JavaVirtualMachines/jdk/Contents/Home",
                "java_path": "/usr/bin/java",
                "sdk_home": "/Users/demo/Library/OpenHarmony/Sdk/15",
                "hvigor_path": str(self.repo_local / "hvigorw"),
                "hvigor_kind": "repo-wrapper",
                "ohpm_path": "/opt/homebrew/bin/ohpm",
                "hdc_path": "/opt/homebrew/bin/hdc",
                "deveco_app": "/Applications/DevEco-Studio.app",
            },
            "candidates": {
                "node_path": ["/opt/homebrew/bin/node"],
                "java_path": ["/usr/bin/java"],
                "sdk_home": ["/Users/demo/Library/OpenHarmony/Sdk/15"],
                "hvigor_path": [str(self.repo_local / "hvigorw")],
                "ohpm_path": ["/opt/homebrew/bin/ohpm"],
                "hdc_path": ["/opt/homebrew/bin/hdc"],
                "deveco_app": ["/Applications/DevEco-Studio.app"],
            },
            "preflight": {"success": True, "exit_code": 0, "output": "tasks"},
            "blockers": [],
        }

    def test_load_cached_detection_hits_when_required_paths_exist(self) -> None:
        with mock.patch.object(HARMONY_BUILD, "cache_root_dir", return_value=self.cache_root):
            HARMONY_BUILD.save_cached_detection(self.ready_result)

        with (
            mock.patch.object(HARMONY_BUILD, "cache_root_dir", return_value=self.cache_root),
            mock.patch.object(HARMONY_BUILD, "host_path_exists", return_value=True),
        ):
            loaded, metadata = HARMONY_BUILD.load_cached_detection(self.repo_info)

        self.assertIsNotNone(loaded)
        self.assertEqual(metadata["source"], "cache")
        self.assertEqual(loaded["cache"]["source"], "cache")
        self.assertTrue(loaded["cache"]["saved"])

    def test_load_cached_detection_rejects_missing_sdk_path(self) -> None:
        with mock.patch.object(HARMONY_BUILD, "cache_root_dir", return_value=self.cache_root):
            HARMONY_BUILD.save_cached_detection(self.ready_result)

        def fake_exists(path_text: str) -> bool:
            return path_text != "/Users/demo/Library/OpenHarmony/Sdk/15"

        with (
            mock.patch.object(HARMONY_BUILD, "cache_root_dir", return_value=self.cache_root),
            mock.patch.object(HARMONY_BUILD, "host_path_exists", side_effect=fake_exists),
        ):
            loaded, metadata = HARMONY_BUILD.load_cached_detection(self.repo_info)

        self.assertIsNone(loaded)
        self.assertEqual(metadata["source"], "stale")
        self.assertEqual(metadata["invalid_reason"], "missing_sdk_home")

    def test_load_cached_detection_migrates_legacy_cache_file(self) -> None:
        legacy_root = Path(self.temp_dir.name) / "legacy-cache"
        with mock.patch.object(HARMONY_BUILD, "cache_root_dir", return_value=legacy_root):
            HARMONY_BUILD.save_cached_detection(self.ready_result)

        legacy_cache_file = next(legacy_root.glob("*.json"))
        self.assertFalse(any(self.cache_root.glob("*.json")))

        with (
            mock.patch.object(HARMONY_BUILD, "cache_root_dir", return_value=self.cache_root),
            mock.patch.object(HARMONY_BUILD, "legacy_cache_root_dir", return_value=legacy_root),
            mock.patch.object(HARMONY_BUILD, "host_path_exists", return_value=True),
        ):
            loaded, metadata = HARMONY_BUILD.load_cached_detection(self.repo_info)

        self.assertIsNotNone(loaded)
        self.assertEqual(metadata["source"], "cache")
        self.assertTrue((self.cache_root / legacy_cache_file.name).exists())

    def test_resolve_detection_refresh_bypasses_cache(self) -> None:
        with (
            mock.patch.object(HARMONY_BUILD, "resolve_repo_paths", return_value=self.repo_info),
            mock.patch.object(HARMONY_BUILD, "load_cached_detection", return_value=(self.ready_result, {"source": "cache"})),
            mock.patch.object(HARMONY_BUILD, "detect_environment_for_repo", return_value=self.ready_result) as detect_mock,
            mock.patch.object(HARMONY_BUILD, "save_cached_detection", return_value={"source": "fresh", "saved": True}) as save_mock,
        ):
            result = HARMONY_BUILD.resolve_detection(
                str(self.repo_local),
                preflight=True,
                refresh=True,
                allow_cache=True,
            )

        detect_mock.assert_called_once()
        save_mock.assert_called_once()
        self.assertEqual(result["cache"]["source"], "fresh")

    def test_resolve_verification_detection_skips_preflight_when_cache_missing(self) -> None:
        static_result = {**self.ready_result, "preflight": None}
        with (
            mock.patch.object(HARMONY_BUILD, "resolve_repo_paths", return_value=self.repo_info),
            mock.patch.object(HARMONY_BUILD, "load_cached_detection", return_value=(None, {"source": "miss"})),
            mock.patch.object(HARMONY_BUILD, "detect_environment_for_repo", return_value=static_result) as detect_mock,
            mock.patch.object(HARMONY_BUILD, "cache_root_dir", return_value=self.cache_root),
        ):
            result = HARMONY_BUILD.resolve_verification_detection(str(self.repo_local), refresh=False)

        detect_mock.assert_called_once_with(self.repo_info, preflight=False)
        self.assertIsNone(result["preflight"])
        self.assertFalse(result["cache"]["saved"])

    def test_cache_root_dir_uses_shared_skills_hub_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"SKILLS_HUB_RUNTIME_DIR": temp_dir}, clear=False):
                cache_root = HARMONY_BUILD.cache_root_dir()

        self.assertEqual((Path(temp_dir) / "harmony-build").resolve(), cache_root)


class HarmonyBuildRegressionTests(unittest.TestCase):
    def test_node_home_derives_parent_from_bin_path(self) -> None:
        node_path = str(Path("/opt/homebrew/bin/node"))
        self.assertEqual(HARMONY_BUILD.node_home_from_path(node_path), str(Path(node_path).parent.parent))

    def test_detect_environment_skip_preflight_uses_static_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "build-profile.json5").write_text("{}", encoding="utf-8")
            (repo / "hvigorw").write_text("#!/bin/sh\n", encoding="utf-8")
            repo_info = {"input": str(repo), "local_path": str(repo), "local_exists": True}

            with (
                mock.patch.object(HARMONY_BUILD, "resolve_node", return_value=("/opt/homebrew", "/opt/homebrew/bin/node", [])),
                mock.patch.object(HARMONY_BUILD, "resolve_java", return_value=(None, None, [])),
                mock.patch.object(HARMONY_BUILD, "resolve_sdk_root", return_value=("/sdk/15", ["/sdk/15"])),
                mock.patch.object(HARMONY_BUILD, "resolve_hvigor_path", return_value=(str(repo / "hvigorw"), [str(repo / "hvigorw")], "repo-wrapper")),
                mock.patch.object(HARMONY_BUILD, "resolve_optional_tool", return_value=(None, [])),
                mock.patch.object(HARMONY_BUILD, "candidate_deveco_apps", return_value=[]),
                mock.patch.object(HARMONY_BUILD, "run_hvigor_task") as run_mock,
            ):
                result = HARMONY_BUILD.detect_environment_for_repo(repo_info, preflight=False)

        self.assertTrue(result["ready"])
        self.assertIsNone(result["preflight"])
        run_mock.assert_not_called()

    def test_detect_environment_reports_missing_project_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            repo_info = {"input": str(repo), "local_path": str(repo), "local_exists": True}

            with (
                mock.patch.object(HARMONY_BUILD, "resolve_node", return_value=("/opt/homebrew", "/opt/homebrew/bin/node", [])),
                mock.patch.object(HARMONY_BUILD, "resolve_java", return_value=(None, None, [])),
                mock.patch.object(HARMONY_BUILD, "resolve_sdk_root", return_value=("/sdk/15", ["/sdk/15"])),
                mock.patch.object(HARMONY_BUILD, "resolve_hvigor_path", return_value=("/repo/hvigorw", ["/repo/hvigorw"], "repo-wrapper")),
                mock.patch.object(HARMONY_BUILD, "resolve_optional_tool", return_value=(None, [])),
                mock.patch.object(HARMONY_BUILD, "candidate_deveco_apps", return_value=[]),
            ):
                result = HARMONY_BUILD.detect_environment_for_repo(repo_info, preflight=False)

        self.assertFalse(result["ready"])
        self.assertIn("harmony_project_markers_missing", result["blockers"])

    def test_print_env_snippet_escapes_shell_literals(self) -> None:
        result = {
            "repo": {"local_path": "/Users/o'connor/work/demo"},
            "resolved": {
                "node_home": "/opt/homebrew",
                "java_home": "/Library/Java/JavaVirtualMachines/jdk/Contents/Home",
                "sdk_home": "/Users/o'connor/Library/OpenHarmony/Sdk/15",
            },
        }

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            HARMONY_BUILD.print_env_snippet(result)

        output = buffer.getvalue()
        self.assertIn("export DEVECO_SDK_HOME='/Users/o'\"'\"'connor/Library/OpenHarmony/Sdk/15'", output)
        self.assertIn("export NODE_HOME=/opt/homebrew", output)
        self.assertIn("cd '/Users/o'\"'\"'connor/work/demo'", output)

    def test_candidate_sdk_roots_includes_discovered_version_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sdk_root = Path(temp_dir) / "Sdk"
            sdk_version = sdk_root / "15"
            (sdk_version / "ets").mkdir(parents=True)

            with (
                mock.patch.dict(os.environ, {"DEVECO_SDK_HOME": str(sdk_root)}, clear=False),
                mock.patch.object(HARMONY_BUILD, "candidate_deveco_apps", return_value=[]),
            ):
                candidates = HARMONY_BUILD.candidate_sdk_roots()

        self.assertIn(str(sdk_version.resolve()), candidates)

    def test_run_hvigor_task_redirects_output_to_file_not_pipe(self) -> None:
        repo_path = Path("/repo")
        hvigor_path = repo_path / "hvigorw"

        def fake_popen(args, **kwargs):
            self.assertEqual(args, [str(hvigor_path), "assembleApp"])
            self.assertEqual(kwargs.get("cwd"), repo_path)
            self.assertIsNotNone(kwargs.get("stdout"))
            self.assertEqual(kwargs.get("stderr"), HARMONY_BUILD.subprocess.STDOUT)
            self.assertNotIn("timeout", kwargs)
            kwargs["stdout"].write("line before\nBUILD SUCCESSFUL in 1 s\n")
            return mock.Mock(pid=4321, wait=mock.Mock(return_value=0))

        with (
            mock.patch.object(HARMONY_BUILD, "is_executable_file", return_value=True),
            mock.patch.object(HARMONY_BUILD.subprocess, "Popen", side_effect=fake_popen) as popen_mock,
        ):
            outcome = HARMONY_BUILD.run_hvigor_task(
                str(repo_path),
                "/sdk/15",
                str(hvigor_path),
                "assembleApp",
                timeout_seconds=12,
            )

        popen_mock.assert_called_once()
        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["exit_code"], 0)
        self.assertIn("BUILD SUCCESSFUL", outcome["output"])

    def test_run_hvigor_task_times_out_and_terminates_process_tree(self) -> None:
        fake_process = mock.Mock(pid=4321)
        fake_process.wait.side_effect = HARMONY_BUILD.subprocess.TimeoutExpired(cmd=["hvigorw"], timeout=1)

        def fake_popen(args, **kwargs):
            kwargs["stdout"].write("BUILD FAILED in 1 s\n")
            return fake_process

        with (
            mock.patch.object(HARMONY_BUILD, "is_executable_file", return_value=True),
            mock.patch.object(HARMONY_BUILD.subprocess, "Popen", side_effect=fake_popen),
            mock.patch.object(HARMONY_BUILD, "terminate_process_tree", return_value=None) as terminate_mock,
        ):
            outcome = HARMONY_BUILD.run_hvigor_task(
                "/repo",
                "/sdk/15",
                "/repo/hvigorw",
                "tasks",
                timeout_seconds=1,
            )

        terminate_mock.assert_called_once_with(fake_process)
        self.assertFalse(outcome["success"])
        self.assertEqual(outcome["exit_code"], 124)
        self.assertIn("BUILD FAILED", outcome["output"])
        self.assertIn("timed out after 1 seconds", outcome["output"])

    def test_run_hvigor_task_rejects_internal_task_key(self) -> None:
        with mock.patch.object(HARMONY_BUILD.subprocess, "Popen") as popen_mock:
            outcome = HARMONY_BUILD.run_hvigor_task(
                "/repo",
                "/sdk/15",
                "/repo/hvigorw",
                r":entry:default@CompileArkTS",
            )

        popen_mock.assert_not_called()
        self.assertFalse(outcome["success"])
        self.assertEqual(outcome["exit_code"], 2)
        self.assertIn("not an internal .hvigor task key", outcome["output"])


if __name__ == "__main__":
    unittest.main()
