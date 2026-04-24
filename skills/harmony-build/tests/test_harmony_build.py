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
            "windows_path": r"D:\workspace\demo",
            "wsl_path": str(self.repo_local),
            "windows_compatible": True,
            "local_exists": True,
        }
        self.ready_result = {
            "ready": True,
            "runtime": {"host": "wsl"},
            "repo": dict(self.repo_info),
            "resolved": {
                "node_home": r"C:\Program Files\nodejs",
                "node_path": r"C:\Program Files\nodejs\node.exe",
                "deveco_sdk_home": r"C:\Huawei\Sdk",
                "hvigorw_path": r"C:\Huawei\hvigorw.bat",
            },
            "candidates": {
                "node_home": [r"C:\Program Files\nodejs"],
                "deveco_sdk_home": [r"C:\Huawei\Sdk"],
                "hvigorw_path": [r"C:\Huawei\hvigorw.bat"],
            },
            "registry_env": {},
            "lookups": {"node": [], "npm_cmd": [], "hvigorw": []},
            "sdk_probes": [],
            "nvm_residue": [],
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
            return path_text != r"C:\Huawei\Sdk"

        with (
            mock.patch.object(HARMONY_BUILD, "cache_root_dir", return_value=self.cache_root),
            mock.patch.object(HARMONY_BUILD, "host_path_exists", side_effect=fake_exists),
        ):
            loaded, metadata = HARMONY_BUILD.load_cached_detection(self.repo_info)

        self.assertIsNone(loaded)
        self.assertEqual(metadata["source"], "stale")
        self.assertEqual(metadata["invalid_reason"], "missing_deveco_sdk_home")

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
                probe_sdk_roots=True,
                refresh=True,
                allow_cache=True,
            )

        detect_mock.assert_called_once_with(self.repo_info, probe_sdk_roots=True)
        save_mock.assert_called_once()
        self.assertEqual(result["cache"]["source"], "fresh")

    def test_cache_root_dir_uses_shared_skills_hub_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"SKILLS_HUB_RUNTIME_DIR": temp_dir}, clear=False):
                cache_root = HARMONY_BUILD.cache_root_dir()

        self.assertEqual((Path(temp_dir) / "harmony-build").resolve(), cache_root)


class HarmonyBuildRegressionTests(unittest.TestCase):
    def test_resolve_node_home_derives_parent_from_windows_lookup_path(self) -> None:
        with mock.patch.object(
            HARMONY_BUILD,
            "host_path_exists",
            side_effect=lambda path_text: path_text == r"C:\Custom\Node\node.exe",
        ):
            node_home, node_path, candidates = HARMONY_BUILD.resolve_node_home(
                {"nodeHomeUser": None, "nodeHomeMachine": None},
                {"node": [r"C:\Custom\Node\node.exe"]},
            )

        self.assertEqual(node_home, r"C:\Custom\Node")
        self.assertEqual(node_path, r"C:\Custom\Node\node.exe")
        self.assertIn(r"C:\Custom\Node", candidates)
        self.assertNotIn(".", candidates)

    def test_skip_sdk_probe_requires_existing_sdk_path(self) -> None:
        repo_info = {
            "input": "/tmp/repo",
            "local_path": "/tmp/repo",
            "windows_path": r"D:\workspace\demo",
            "wsl_path": "/tmp/repo",
            "windows_compatible": True,
            "local_exists": True,
        }

        with (
            mock.patch.object(HARMONY_BUILD, "gather_windows_env", return_value={"devecoSdkHomeUser": r"C:\Missing\Sdk"}),
            mock.patch.object(HARMONY_BUILD, "gather_lookup_paths", return_value={}),
            mock.patch.object(
                HARMONY_BUILD,
                "resolve_node_home",
                return_value=(r"C:\Custom\Node", r"C:\Custom\Node\node.exe", [r"C:\Custom\Node"]),
            ),
            mock.patch.object(
                HARMONY_BUILD,
                "resolve_hvigorw_path",
                return_value=(r"C:\Huawei\hvigorw.bat", [r"C:\Huawei\hvigorw.bat"]),
            ),
            mock.patch.object(HARMONY_BUILD, "candidate_sdk_roots", return_value=[]),
            mock.patch.object(HARMONY_BUILD, "detect_nvm_residue", return_value=[]),
            mock.patch.object(HARMONY_BUILD, "host_path_exists", return_value=False),
        ):
            result = HARMONY_BUILD.detect_environment_for_repo(repo_info, probe_sdk_roots=False)

        self.assertFalse(result["ready"])
        self.assertIsNone(result["resolved"]["deveco_sdk_home"])

    def test_print_env_snippet_escapes_powershell_literals(self) -> None:
        result = {
            "repo": {"windows_path": r"C:\Users\O'Connor\repo"},
            "resolved": {
                "node_home": r"C:\Users\O'Connor\node",
                "deveco_sdk_home": r"C:\Sdk\O'Connor",
            },
        }

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            HARMONY_BUILD.print_env_snippet(result)

        output = buffer.getvalue()
        self.assertIn("$env:NODE_HOME = 'C:\\Users\\O''Connor\\node'", output)
        self.assertIn("$env:DEVECO_SDK_HOME = 'C:\\Sdk\\O''Connor'", output)
        self.assertIn("Set-Location 'C:\\Users\\O''Connor\\repo'", output)

    def test_candidate_sdk_roots_includes_discovered_version_directories(self) -> None:
        sdk_root = r"C:\Users\Demo\AppData\Local\OpenHarmony\Sdk"
        sdk_version = r"C:\Users\Demo\AppData\Local\OpenHarmony\Sdk\24"

        with (
            mock.patch.object(
                HARMONY_BUILD,
                "host_path_exists",
                side_effect=lambda path_text: path_text in {sdk_root, sdk_version},
            ),
            mock.patch.object(
                HARMONY_BUILD,
                "host_dir_children",
                side_effect=lambda path_text: [sdk_version] if path_text == sdk_root else [],
            ),
        ):
            candidates = HARMONY_BUILD.candidate_sdk_roots({"userProfile": r"C:\Users\Demo"})

        self.assertIn(sdk_root, candidates)
        self.assertIn(sdk_version, candidates)

    def test_run_hvigor_task_redirects_output_to_file_not_pipe(self) -> None:
        def fake_popen(args, **kwargs):
            self.assertNotIn("capture_output", kwargs)
            self.assertIsNotNone(kwargs.get("stdout"))
            self.assertEqual(kwargs.get("stderr"), HARMONY_BUILD.subprocess.STDOUT)
            self.assertNotIn("timeout", kwargs)
            kwargs["stdout"].write(f"{HARMONY_BUILD.POWERSHELL_PID_MARKER}4321\n")
            kwargs["stdout"].write("line before\nBUILD SUCCESSFUL in 1 s\n")
            return mock.Mock(pid=4321, wait=mock.Mock(return_value=0))

        with mock.patch.object(HARMONY_BUILD.subprocess, "Popen", side_effect=fake_popen) as popen_mock:
            outcome = HARMONY_BUILD.run_hvigor_task(
                r"D:\workspace\demo",
                r"C:\Node",
                r"C:\Sdk",
                r"C:\Huawei\hvigorw.bat",
                "assembleApp",
                timeout_seconds=12,
            )

        popen_mock.assert_called_once()
        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["exit_code"], 0)
        self.assertIn("BUILD SUCCESSFUL", outcome["output"])
        self.assertNotIn(HARMONY_BUILD.POWERSHELL_PID_MARKER, outcome["output"])

    def test_run_hvigor_task_times_out_and_terminates_process_tree(self) -> None:
        fake_process = mock.Mock(pid=4321)
        fake_process.wait.side_effect = HARMONY_BUILD.subprocess.TimeoutExpired(cmd=["powershell.exe"], timeout=1)

        def fake_popen(args, **kwargs):
            kwargs["stdout"].write(f"{HARMONY_BUILD.POWERSHELL_PID_MARKER}9876\n")
            kwargs["stdout"].write("BUILD FAILED in 1 s\n")
            return fake_process

        with (
            mock.patch.object(HARMONY_BUILD.subprocess, "Popen", side_effect=fake_popen),
            mock.patch.object(HARMONY_BUILD, "terminate_process_tree", return_value=None) as terminate_mock,
        ):
            outcome = HARMONY_BUILD.run_hvigor_task(
                r"D:\workspace\demo",
                r"C:\Node",
                r"C:\Sdk",
                r"C:\Huawei\hvigorw.bat",
                "tasks",
                timeout_seconds=1,
            )

        terminate_mock.assert_called_once_with(fake_process, 9876)
        self.assertFalse(outcome["success"])
        self.assertEqual(outcome["exit_code"], 124)
        self.assertIn("BUILD FAILED", outcome["output"])
        self.assertIn("timed out after 1 seconds", outcome["output"])
        self.assertNotIn(HARMONY_BUILD.POWERSHELL_PID_MARKER, outcome["output"])

    def test_run_hvigor_task_rejects_internal_task_key(self) -> None:
        with mock.patch.object(HARMONY_BUILD.subprocess, "Popen") as popen_mock:
            outcome = HARMONY_BUILD.run_hvigor_task(
                r"D:\workspace\demo",
                r"C:\Node",
                r"C:\Sdk",
                r"C:\Huawei\hvigorw.bat",
                r":entry:default@CompileArkTS",
            )

        popen_mock.assert_not_called()
        self.assertFalse(outcome["success"])
        self.assertEqual(outcome["exit_code"], 2)
        self.assertIn("not an internal .hvigor task key", outcome["output"])

    def test_terminate_process_tree_uses_windows_taskkill(self) -> None:
        fake_process = mock.Mock(pid=4321)
        taskkill_result = mock.Mock(returncode=0)

        with mock.patch.object(HARMONY_BUILD.subprocess, "run", return_value=taskkill_result) as run_mock:
            cleanup_error = HARMONY_BUILD.terminate_process_tree(fake_process, 9876)

        self.assertIsNone(cleanup_error)
        run_mock.assert_called_once_with(
            ["taskkill.exe", "/PID", "9876", "/T", "/F"],
            stdout=HARMONY_BUILD.subprocess.DEVNULL,
            stderr=HARMONY_BUILD.subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        fake_process.wait.assert_called_once_with(timeout=10)


if __name__ == "__main__":
    unittest.main()
