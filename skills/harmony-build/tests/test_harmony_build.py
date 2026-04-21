import io
import importlib.util
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


if __name__ == "__main__":
    unittest.main()
