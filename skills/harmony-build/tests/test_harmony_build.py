import io
import importlib.util
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
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
        self.node_path = Path(self.temp_dir.name) / "tools" / "node"
        self.node_path.parent.mkdir()
        self.node_path.write_text("#!/bin/sh\n", encoding="utf-8")
        self.node_path.chmod(0o755)
        self.hvigor_path = self.repo_local / "hvigorw"
        self.hvigor_path.write_text("#!/bin/sh\n", encoding="utf-8")
        self.hvigor_path.chmod(0o755)
        self.sdk_home = Path(self.temp_dir.name) / "Sdk" / "15"
        self.sdk_home.mkdir(parents=True)
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
                "node_path": str(self.node_path),
                "java_home": "/Library/Java/JavaVirtualMachines/jdk/Contents/Home",
                "java_path": "/usr/bin/java",
                "sdk_home": str(self.sdk_home),
                "hvigor_path": str(self.hvigor_path),
                "hvigor_kind": "repo-wrapper",
                "ohpm_path": "/opt/homebrew/bin/ohpm",
                "hdc_path": "/opt/homebrew/bin/hdc",
                "deveco_app": "/Applications/DevEco-Studio.app",
            },
            "candidates": {
                "node_path": [str(self.node_path)],
                "java_path": ["/usr/bin/java"],
                "sdk_home": [str(self.sdk_home)],
                "hvigor_path": [str(self.hvigor_path)],
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
            return path_text != str(self.sdk_home)

        with (
            mock.patch.object(HARMONY_BUILD, "cache_root_dir", return_value=self.cache_root),
            mock.patch.object(HARMONY_BUILD, "host_path_exists", side_effect=fake_exists),
        ):
            loaded, metadata = HARMONY_BUILD.load_cached_detection(self.repo_info)

        self.assertIsNone(loaded)
        self.assertEqual(metadata["source"], "stale")
        self.assertEqual(metadata["invalid_reason"], "missing_sdk_home")

    def test_load_cached_detection_rejects_non_executable_tool_paths(self) -> None:
        for label, target_path in (("node_path", self.node_path), ("hvigor_path", self.hvigor_path)):
            with self.subTest(label=label):
                with mock.patch.object(HARMONY_BUILD, "cache_root_dir", return_value=self.cache_root):
                    HARMONY_BUILD.save_cached_detection(self.ready_result)

                def fake_is_executable(path: Path) -> bool:
                    return Path(path) != target_path

                with (
                    mock.patch.object(HARMONY_BUILD, "cache_root_dir", return_value=self.cache_root),
                    mock.patch.object(HARMONY_BUILD, "host_path_exists", return_value=True),
                    mock.patch.object(HARMONY_BUILD, "is_executable_file", side_effect=fake_is_executable),
                ):
                    loaded, metadata = HARMONY_BUILD.load_cached_detection(self.repo_info)

                self.assertIsNone(loaded)
                self.assertEqual(metadata["source"], "stale")
                self.assertEqual(metadata["invalid_reason"], f"not_executable_{label}")

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

    def test_resolve_detection_passes_preflight_timeout_and_progress(self) -> None:
        messages = []
        progress = messages.append
        with (
            mock.patch.object(HARMONY_BUILD, "resolve_repo_paths", return_value=self.repo_info),
            mock.patch.object(HARMONY_BUILD, "load_cached_detection", return_value=(None, {"source": "miss"})),
            mock.patch.object(HARMONY_BUILD, "detect_environment_for_repo", return_value=self.ready_result) as detect_mock,
            mock.patch.object(HARMONY_BUILD, "save_cached_detection", return_value={"source": "fresh", "saved": True}),
        ):
            HARMONY_BUILD.resolve_detection(
                str(self.repo_local),
                preflight=True,
                refresh=False,
                allow_cache=True,
                timeout_seconds=17,
                progress=progress,
            )

        detect_mock.assert_called_once_with(
            self.repo_info,
            preflight=True,
            timeout_seconds=17,
            progress=progress,
        )

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

    def test_macos_usr_bin_java_uses_libexec_java_home(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(HARMONY_BUILD, "RUNTIME", "macos"),
            mock.patch.object(HARMONY_BUILD, "resolve_macos_java_home", return_value="/Library/Java/JDK/Contents/Home") as java_home_mock,
        ):
            java_home = HARMONY_BUILD.java_home_from_path("/usr/bin/java")

        self.assertEqual(java_home, "/Library/Java/JDK/Contents/Home")
        java_home_mock.assert_called_once_with()

    def test_macos_explicit_java_home_wins_over_libexec_java_home(self) -> None:
        with (
            mock.patch.dict(os.environ, {"JAVA_HOME": "/A"}, clear=True),
            mock.patch.object(HARMONY_BUILD, "RUNTIME", "macos"),
            mock.patch.object(HARMONY_BUILD, "candidate_java_paths", return_value=["/A/bin/java"]),
            mock.patch.object(HARMONY_BUILD, "is_executable_file", return_value=True),
            mock.patch.object(HARMONY_BUILD, "resolve_macos_java_home", return_value="/B") as java_home_mock,
        ):
            java_home, java_path, candidates = HARMONY_BUILD.resolve_java()

        self.assertEqual(java_home, "/A")
        self.assertEqual(java_path, "/A/bin/java")
        self.assertEqual(candidates, ["/A/bin/java"])
        java_home_mock.assert_not_called()

    def test_doctor_collects_versions_java_home_verbose_and_sdk_components(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sdk_root = Path(temp_dir) / "Sdk" / "15"
            (sdk_root / "ets").mkdir(parents=True)
            (sdk_root / "toolchains").mkdir()
            detection = {
                "resolved": {
                    "node_path": "/tools/node",
                    "java_path": "/tools/java",
                    "ohpm_path": "/tools/ohpm",
                    "hdc_path": "/tools/hdc",
                    "sdk_home": str(sdk_root),
                    "deveco_app": "/Applications/DevEco-Studio.app",
                },
                "candidates": {
                    "sdk_home": [str(sdk_root)],
                    "deveco_app": ["/Applications/DevEco-Studio.app"],
                },
            }

            def fake_run(args, **kwargs):
                self.assertFalse(kwargs.get("check"))
                self.assertTrue(kwargs.get("capture_output"))
                java_home_helper = str(HARMONY_BUILD.macos_java_home_helper_path())
                output = {
                    ("/tools/node", "--version"): ("v20.11.1\n", ""),
                    ("/tools/java", "-version"): ("", 'openjdk version "17.0.10"\n'),
                    ("/tools/ohpm", "--version"): ("5.0.0\n", ""),
                    ("/tools/hdc", "-v"): ("Ver: 3.1.0\n", ""),
                    (java_home_helper, "-V"): ("", 'Matching Java Virtual Machines (1):\n17.0.10, x86_64: "JDK 17"\n'),
                }[tuple(args)]
                return HARMONY_BUILD.subprocess.CompletedProcess(args, 0, stdout=output[0], stderr=output[1])

            with (
                mock.patch.object(HARMONY_BUILD.subprocess, "run", side_effect=fake_run) as run_mock,
                mock.patch.object(HARMONY_BUILD, "RUNTIME", "macos"),
                mock.patch.object(HARMONY_BUILD, "macos_java_home_helper_exists", return_value=True),
            ):
                report = HARMONY_BUILD.build_doctor_report_from_detection(detection)

        self.assertEqual(report["tools"]["node"]["version"], "v20.11.1")
        self.assertIn('openjdk version "17.0.10"', report["tools"]["java"]["version"])
        self.assertEqual(report["tools"]["ohpm"]["version"], "5.0.0")
        self.assertEqual(report["tools"]["hdc"]["version"], "Ver: 3.1.0")
        self.assertIn("JDK 17", "\n".join(report["macos_java_home"]["summary"]))
        self.assertEqual(report["sdk"]["candidates"][0]["api"], "15")
        self.assertEqual(report["sdk"]["candidates"][0]["components"], ["ets", "toolchains"])
        self.assertEqual(run_mock.call_count, 5)

    def test_doctor_command_returns_zero_even_when_environment_is_not_ready(self) -> None:
        report = {
            "detection": {
                "ready": False,
                "blockers": ["sdk_missing"],
            },
            "doctor": {
                "tools": {},
                "macos_java_home": {"available": False, "summary": []},
                "sdk": {"selected": None, "candidates": []},
                "deveco": {"selected": None, "candidates": []},
            },
        }

        with (
            mock.patch.object(sys, "argv", ["harmony_build.py", "doctor", "--repo", "/repo", "--json"]),
            mock.patch.object(HARMONY_BUILD, "build_doctor_report", return_value=report),
            redirect_stdout(io.StringIO()) as output,
        ):
            exit_code = HARMONY_BUILD.main()

        self.assertEqual(exit_code, 0)
        self.assertIn('"ready": false', output.getvalue())

    def test_verify_command_requires_explicit_task(self) -> None:
        with (
            mock.patch.object(sys, "argv", ["harmony_build.py", "verify", "--repo", "/repo"]),
            mock.patch.object(HARMONY_BUILD, "resolve_verification_detection") as detect_mock,
            redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as error,
        ):
            HARMONY_BUILD.main()

        self.assertEqual(error.exception.code, 2)
        detect_mock.assert_not_called()

    def test_verify_tasks_does_not_save_ready_baseline(self) -> None:
        detection = {
            "ready": True,
            "repo": {"input": "/repo", "local_path": "/repo", "local_exists": True},
            "resolved": {"sdk_home": "/sdk", "hvigor_path": "/repo/hvigorw"},
            "cache": {"source": "fresh", "saved": False},
        }
        outcome = {
            "success": True,
            "exit_code": 0,
            "output": "tasks",
            "timed_out": False,
        }

        with (
            mock.patch.object(sys, "argv", ["harmony_build.py", "verify", "--repo", "/repo", "--task", "tasks", "--json"]),
            mock.patch.object(HARMONY_BUILD, "resolve_verification_detection", return_value=detection),
            mock.patch.object(HARMONY_BUILD, "verify_task", return_value=outcome) as verify_mock,
            mock.patch.object(HARMONY_BUILD, "save_cached_detection") as save_mock,
            redirect_stdout(io.StringIO()) as output,
        ):
            exit_code = HARMONY_BUILD.main()

        self.assertEqual(exit_code, 0)
        verify_mock.assert_called_once_with(detection, "tasks", HARMONY_BUILD.HVIGOR_TASK_TIMEOUT_SECONDS)
        save_mock.assert_not_called()
        self.assertIn('"task": "tasks"', output.getvalue())

    def test_macos_usr_bin_java_without_libexec_does_not_return_usr(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(HARMONY_BUILD, "RUNTIME", "macos"),
            mock.patch.object(HARMONY_BUILD, "resolve_macos_java_home", return_value=None),
        ):
            java_home = HARMONY_BUILD.java_home_from_path("/usr/bin/java")

        self.assertIsNone(java_home)

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

    def test_detect_environment_preflight_uses_configured_timeout_and_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "build-profile.json5").write_text("{}", encoding="utf-8")
            repo_info = {"input": str(repo), "local_path": str(repo), "local_exists": True}
            messages = []

            with (
                mock.patch.object(HARMONY_BUILD, "resolve_node", return_value=("/node", "/node/bin/node", [])),
                mock.patch.object(HARMONY_BUILD, "resolve_java", return_value=("/java", "/java/bin/java", [])),
                mock.patch.object(HARMONY_BUILD, "resolve_sdk_root", return_value=("/sdk/15", ["/sdk/15"])),
                mock.patch.object(HARMONY_BUILD, "resolve_hvigor_path", return_value=("/repo/hvigorw", ["/repo/hvigorw"], "repo-wrapper")),
                mock.patch.object(HARMONY_BUILD, "resolve_optional_tool", return_value=(None, [])),
                mock.patch.object(HARMONY_BUILD, "candidate_deveco_apps", return_value=[]),
                mock.patch.object(
                    HARMONY_BUILD,
                    "run_hvigor_task",
                    return_value={"success": True, "exit_code": 0, "output": "tasks", "timed_out": False},
                ) as run_mock,
            ):
                result = HARMONY_BUILD.detect_environment_for_repo(
                    repo_info,
                    preflight=True,
                    timeout_seconds=7,
                    progress=messages.append,
                )

        self.assertTrue(result["ready"])
        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.kwargs["timeout_seconds"], 7)
        self.assertIn("timeout 7s", messages[0])

    def test_iter_project_config_files_prunes_ignored_dirs_before_descent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)

            def fake_walk(root):
                self.assertEqual(Path(root), repo)
                dirnames = ["node_modules", "entry"]
                yield str(repo), dirnames, []
                self.assertEqual(["entry"], dirnames)
                yield str(repo / "entry"), [], ["build-profile.json5"]

            with mock.patch.object(HARMONY_BUILD.os, "walk", side_effect=fake_walk):
                paths = list(HARMONY_BUILD.iter_project_config_files(repo, "build-profile.json5"))

        self.assertEqual([repo / "entry" / "build-profile.json5"], paths)

    def test_list_tasks_default_timeout_uses_short_task_list_budget(self) -> None:
        args = HARMONY_BUILD.build_parser().parse_args(["list-tasks"])

        self.assertEqual(args.timeout_seconds, HARMONY_BUILD.HVIGOR_TASK_LIST_TIMEOUT_SECONDS)

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

    def test_repo_hvigorw_not_executable_blocks_path_fallback_and_prints_chmod_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "build-profile.json5").write_text("{}", encoding="utf-8")
            wrapper = repo / "hvigorw"
            wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
            repo_info = {"input": str(repo), "local_path": str(repo), "local_exists": True}

            def fake_is_executable(path: Path) -> bool:
                return Path(path) != wrapper

            with (
                mock.patch.object(HARMONY_BUILD, "resolve_node", return_value=("/opt/homebrew", "/opt/homebrew/bin/node", [])),
                mock.patch.object(HARMONY_BUILD, "resolve_java", return_value=("/Library/Java/JDK/Contents/Home", "/usr/bin/java", [])),
                mock.patch.object(HARMONY_BUILD, "resolve_sdk_root", return_value=("/sdk/15", ["/sdk/15"])),
                mock.patch.object(HARMONY_BUILD, "candidate_hvigor_paths", return_value=[str(wrapper), "/usr/local/bin/hvigor"]),
                mock.patch.object(HARMONY_BUILD, "is_executable_file", side_effect=fake_is_executable),
                mock.patch.object(HARMONY_BUILD, "resolve_optional_tool", return_value=(None, [])),
                mock.patch.object(HARMONY_BUILD, "candidate_deveco_apps", return_value=[]),
            ):
                result = HARMONY_BUILD.detect_environment_for_repo(repo_info, preflight=False)

        self.assertFalse(result["ready"])
        self.assertIsNone(result["resolved"]["hvigor_path"])
        self.assertEqual(result["resolved"]["hvigor_kind"], "repo-wrapper-not-executable")
        self.assertIn("hvigor_missing_or_not_executable", result["blockers"])
        self.assertIn("chmod +x hvigorw", result["blocker_details"]["hvigor_missing_or_not_executable"])

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            HARMONY_BUILD.print_detection(result)
        self.assertIn("chmod +x hvigorw", buffer.getvalue())

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
            (sdk_version / "ets" / "oh-uni-package.json").write_text("{}", encoding="utf-8")

            with (
                mock.patch.dict(os.environ, {"DEVECO_SDK_HOME": str(sdk_root)}, clear=False),
                mock.patch.object(HARMONY_BUILD, "candidate_deveco_apps", return_value=[]),
            ):
                candidates = HARMONY_BUILD.candidate_sdk_roots()

        self.assertIn(str(sdk_version.resolve()), candidates)

    def test_resolve_sdk_root_prefers_deveco_harmonyos_sdk_for_harmonyos_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            repo = base / "app"
            repo.mkdir()
            (repo / "build-profile.json5").write_text(
                '{ app: { products: [{ runtimeOS: "HarmonyOS" }] } }\n',
                encoding="utf-8",
            )
            openharmony_sdk = base / "OpenHarmony" / "Sdk"
            (openharmony_sdk / "23" / "ets").mkdir(parents=True)
            (openharmony_sdk / "23" / "ets" / "oh-uni-package.json").write_text("{}", encoding="utf-8")
            deveco_app = base / "DevEco-Studio.app"
            harmony_sdk = deveco_app / "Contents" / "sdk"
            (harmony_sdk / "default" / "hms" / "ets").mkdir(parents=True)
            (harmony_sdk / "default" / "hms" / "ets" / "uni-package.json").write_text("{}", encoding="utf-8")
            (harmony_sdk / "default" / "openharmony" / "ets").mkdir(parents=True)
            (harmony_sdk / "default" / "openharmony" / "ets" / "oh-uni-package.json").write_text("{}", encoding="utf-8")

            with (
                mock.patch.dict(os.environ, {"DEVECO_SDK_HOME": str(openharmony_sdk)}, clear=False),
                mock.patch.object(HARMONY_BUILD, "candidate_deveco_apps", return_value=[str(deveco_app)]),
            ):
                selected, candidates = HARMONY_BUILD.resolve_sdk_root(repo)

        self.assertEqual(selected, str(harmony_sdk.resolve()))
        self.assertIn(str((openharmony_sdk / "23").resolve()), candidates)
        self.assertIn(str(harmony_sdk.resolve()), candidates)

    def test_harmonyos_project_does_not_treat_openharmony_sdk_as_static_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            repo = base / "app"
            repo.mkdir()
            (repo / "build-profile.json5").write_text(
                '{ app: { products: [{ runtimeOS: "HarmonyOS" }] } }\n',
                encoding="utf-8",
            )
            sdk_version = base / "OpenHarmony" / "Sdk" / "23"
            (sdk_version / "ets").mkdir(parents=True)
            (sdk_version / "ets" / "oh-uni-package.json").write_text("{}", encoding="utf-8")
            repo_info = {"input": str(repo), "local_path": str(repo), "local_exists": True}

            with (
                mock.patch.object(HARMONY_BUILD, "resolve_node", return_value=("/node", "/node/bin/node", [])),
                mock.patch.object(HARMONY_BUILD, "resolve_java", return_value=("/java", "/java/bin/java", [])),
                mock.patch.object(HARMONY_BUILD, "candidate_sdk_roots", return_value=[str(sdk_version)]),
                mock.patch.object(HARMONY_BUILD, "resolve_hvigor_path", return_value=("/repo/hvigorw", ["/repo/hvigorw"], "repo-wrapper")),
                mock.patch.object(HARMONY_BUILD, "resolve_optional_tool", return_value=(None, [])),
                mock.patch.object(HARMONY_BUILD, "candidate_deveco_apps", return_value=[]),
            ):
                result = HARMONY_BUILD.detect_environment_for_repo(repo_info, preflight=False)

        self.assertFalse(result["ready"])
        self.assertIsNone(result["resolved"]["sdk_home"])
        self.assertEqual(result["project"]["runtime_os"], "HarmonyOS")
        self.assertIn("sdk_missing", result["blockers"])
        self.assertIn("HarmonyOS", result["blocker_details"]["sdk_missing"])

    def test_read_project_runtime_os_ignores_json5_comments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "build-profile.json5").write_text(
                """
{
  // runtimeOS: "HarmonyOS"
  /*
   * runtimeOS: "HarmonyOS"
   */
  app: { products: [{ runtimeOS: "OpenHarmony" }] }
}
""",
                encoding="utf-8",
            )

            runtime_os = HARMONY_BUILD.read_project_runtime_os(repo)

        self.assertEqual(runtime_os, "OpenHarmony")

    def test_recommend_tasks_maps_pages_resources_and_module_config_to_module_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = HARMONY_BUILD.recommend_tasks_for_paths(
                temp_dir,
                [
                    "entry/src/main/ets/pages/Index.ets",
                    "entry/src/main/resources/base/element/string.json",
                    "entry/build-profile.json5",
                    "feature/oh-package.json5",
                ],
            )

        templates = [item["task_template"] for item in result["recommendations"]]
        self.assertEqual(templates, [":entry:assembleHap", ":entry:assembleHap", ":entry:assembleHap", ":feature:assembleHap"])
        self.assertFalse(result["needs_list_tasks"])
        self.assertEqual(result["recommendations"][0]["kind"], "ets")
        self.assertEqual(result["recommendations"][1]["kind"], "resources")
        self.assertEqual(result["recommendations"][2]["kind"], "module_config")

    def test_recommend_tasks_marks_unknown_paths_for_task_listing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = HARMONY_BUILD.recommend_tasks_for_paths(temp_dir, ["docs/usage.md"])

        self.assertTrue(result["needs_list_tasks"])
        self.assertIsNone(result["recommendations"][0]["task_template"])
        self.assertIn("需先列出公开 hvigor tasks", result["recommendations"][0]["reason"])

    def test_build_project_auto_selects_preferred_public_build_task(self) -> None:
        detection = {
            "ready": True,
            "repo": {"input": "/repo", "local_path": "/repo", "local_exists": True},
            "resolved": {"sdk_home": "/sdk", "hvigor_path": "/repo/hvigorw"},
            "cache": {"source": "cache"},
        }
        tasks_outcome = {
            "success": True,
            "exit_code": 0,
            "output": "tasks - Displays tasks\nassembleApp - Assemble the packaged app\n",
            "timed_out": False,
        }
        build_outcome = {
            "success": True,
            "exit_code": 0,
            "output": "BUILD SUCCESSFUL in 1 s",
            "timed_out": False,
        }

        with (
            mock.patch.object(HARMONY_BUILD, "resolve_verification_detection", return_value=detection),
            mock.patch.object(HARMONY_BUILD, "verify_task", side_effect=[tasks_outcome, build_outcome]) as verify_mock,
        ):
            result = HARMONY_BUILD.build_project("/repo")

        self.assertEqual(result["selected_task"], "assembleApp")
        self.assertTrue(result["verification"]["success"])
        self.assertEqual(result["verification"]["output"], "")
        self.assertEqual(result["task_list"]["output"], "")
        self.assertEqual([call.args[1] for call in verify_mock.call_args_list], ["tasks", "assembleApp"])

    def test_build_project_prefers_public_path_recommendation(self) -> None:
        detection = {
            "ready": True,
            "repo": {"input": "/repo", "local_path": "/repo", "local_exists": True},
            "resolved": {"sdk_home": "/sdk", "hvigor_path": "/repo/hvigorw"},
            "cache": {"source": "cache"},
        }
        tasks_outcome = {
            "success": True,
            "exit_code": 0,
            "output": ":entry:assembleHap - Assemble entry hap\nassembleApp - Assemble the packaged app\n",
            "timed_out": False,
        }
        build_outcome = {
            "success": True,
            "exit_code": 0,
            "output": "BUILD SUCCESSFUL in 1 s",
            "timed_out": False,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            with (
                mock.patch.object(HARMONY_BUILD, "resolve_verification_detection", return_value=detection),
                mock.patch.object(HARMONY_BUILD, "verify_task", side_effect=[tasks_outcome, build_outcome]) as verify_mock,
            ):
                result = HARMONY_BUILD.build_project(str(repo), paths=["entry/src/main/ets/pages/Index.ets"])

        self.assertEqual(result["selected_task"], ":entry:assembleHap")
        self.assertIn("path recommendation", result["selection_reason"])
        self.assertEqual(result["verification"]["output"], "")
        self.assertEqual(result["task_list"]["output"], "")
        self.assertEqual([call.args[1] for call in verify_mock.call_args_list], ["tasks", ":entry:assembleHap"])

    def test_build_project_reports_when_no_public_build_task_can_be_selected(self) -> None:
        detection = {
            "ready": True,
            "repo": {"input": "/repo", "local_path": "/repo", "local_exists": True},
            "resolved": {"sdk_home": "/sdk", "hvigor_path": "/repo/hvigorw"},
            "cache": {"source": "cache"},
        }
        tasks_outcome = {
            "success": True,
            "exit_code": 0,
            "output": "tasks - Displays tasks\ntaskTree - Displays task tree\n",
            "timed_out": False,
        }

        with (
            mock.patch.object(HARMONY_BUILD, "resolve_verification_detection", return_value=detection),
            mock.patch.object(HARMONY_BUILD, "verify_task", return_value=tasks_outcome) as verify_mock,
        ):
            result = HARMONY_BUILD.build_project("/repo")

        self.assertIsNone(result["selected_task"])
        self.assertFalse(result["verification"]["success"])
        self.assertEqual(result["verification"]["exit_code"], 2)
        self.assertEqual(result["task_list"]["output"], "")
        verify_mock.assert_called_once()

    def test_build_project_uses_short_task_list_timeout_and_reports_progress(self) -> None:
        detection = {
            "ready": True,
            "repo": {"input": "/repo", "local_path": "/repo", "local_exists": True},
            "resolved": {"sdk_home": "/sdk", "hvigor_path": "/repo/hvigorw"},
            "cache": {"source": "cache"},
        }
        tasks_outcome = {
            "success": True,
            "exit_code": 0,
            "output": "assembleApp - Assemble the packaged app\n",
            "timed_out": False,
        }
        build_outcome = {
            "success": True,
            "exit_code": 0,
            "output": "BUILD SUCCESSFUL in 1 s",
            "timed_out": False,
        }
        messages = []

        with (
            mock.patch.object(HARMONY_BUILD, "resolve_verification_detection", return_value=detection),
            mock.patch.object(HARMONY_BUILD, "verify_task", side_effect=[tasks_outcome, build_outcome]) as verify_mock,
        ):
            result = HARMONY_BUILD.build_project("/repo", progress=messages.append)

        self.assertTrue(result["verification"]["success"])
        self.assertEqual([call.args[1] for call in verify_mock.call_args_list], ["tasks", "assembleApp"])
        self.assertEqual(
            [call.args[2] for call in verify_mock.call_args_list],
            [HARMONY_BUILD.HVIGOR_TASK_LIST_TIMEOUT_SECONDS, HARMONY_BUILD.HVIGOR_TASK_TIMEOUT_SECONDS],
        )
        self.assertEqual(result["verification"]["phase"], "build")
        self.assertTrue(any("list-tasks" in message for message in messages))
        self.assertTrue(any("build" in message for message in messages))
        self.assertEqual([call.kwargs.get("full_output") for call in verify_mock.call_args_list], [True, None])

    def test_build_project_preserves_task_listing_timeout_as_final_failure(self) -> None:
        detection = {
            "ready": True,
            "repo": {"input": "/repo", "local_path": "/repo", "local_exists": True},
            "resolved": {"sdk_home": "/sdk", "hvigor_path": "/repo/hvigorw"},
            "cache": {"source": "cache"},
        }
        tasks_outcome = {
            "success": False,
            "exit_code": 124,
            "output": "hvigor task timed out after 120 seconds.",
            "timed_out": True,
            "duration_seconds": 120.0,
        }

        with (
            mock.patch.object(HARMONY_BUILD, "resolve_verification_detection", return_value=detection),
            mock.patch.object(HARMONY_BUILD, "verify_task", return_value=tasks_outcome) as verify_mock,
        ):
            result = HARMONY_BUILD.build_project("/repo")

        verify_mock.assert_called_once()
        self.assertIsNone(result["selected_task"])
        self.assertTrue(result["verification"]["timed_out"])
        self.assertEqual(result["verification"]["exit_code"], 124)
        self.assertEqual(result["verification"]["phase"], "list-tasks")
        self.assertEqual(result["verification"]["task"], "tasks")
        self.assertIn("timed out", result["verification"]["output"])

    def test_build_project_stops_when_deadline_exhausted_before_build_task(self) -> None:
        detection = {
            "ready": True,
            "repo": {"input": "/repo", "local_path": "/repo", "local_exists": True},
            "resolved": {"sdk_home": "/sdk", "hvigor_path": "/repo/hvigorw"},
            "cache": {"source": "cache"},
        }
        tasks_outcome = {
            "success": True,
            "exit_code": 0,
            "output": "assembleApp - Assemble the packaged app\n",
            "timed_out": False,
        }

        with (
            mock.patch.object(HARMONY_BUILD, "resolve_verification_detection", return_value=detection),
            mock.patch.object(HARMONY_BUILD, "verify_task", return_value=tasks_outcome) as verify_mock,
            mock.patch.object(HARMONY_BUILD.time, "monotonic", side_effect=[100.0, 100.0, 103.1, 103.1]),
        ):
            result = HARMONY_BUILD.build_project("/repo", timeout_seconds=3, list_timeout_seconds=3)

        verify_mock.assert_called_once()
        self.assertEqual(verify_mock.call_args.args[1], "tasks")
        self.assertEqual(verify_mock.call_args.args[2], 3)
        self.assertEqual(result["selected_task"], "assembleApp")
        self.assertFalse(result["verification"]["success"])
        self.assertTrue(result["verification"]["timed_out"])
        self.assertEqual(result["verification"]["exit_code"], 124)
        self.assertEqual(result["verification"]["phase"], "build")

    def test_build_project_task_listing_retry_uses_remaining_deadline(self) -> None:
        cached_detection = {
            "ready": True,
            "repo": {"input": "/repo", "local_path": "/repo", "local_exists": True},
            "resolved": {"sdk_home": "/stale-sdk", "hvigor_path": "/repo/hvigorw"},
            "cache": {"source": "cache"},
        }
        fresh_detection = {
            "ready": True,
            "repo": {"input": "/repo", "local_path": "/repo", "local_exists": True},
            "resolved": {"sdk_home": "/fresh-sdk", "hvigor_path": "/repo/hvigorw"},
            "cache": {"source": "fresh"},
        }
        env_failure = {
            "success": False,
            "exit_code": 1,
            "output": "SDK component missing",
            "timed_out": False,
        }
        tasks_outcome = {
            "success": True,
            "exit_code": 0,
            "output": "assembleApp - Assemble the packaged app\n",
            "timed_out": False,
        }
        build_outcome = {
            "success": True,
            "exit_code": 0,
            "output": "BUILD SUCCESSFUL in 1 s",
            "timed_out": False,
        }

        with (
            mock.patch.object(HARMONY_BUILD, "resolve_verification_detection", side_effect=[cached_detection, fresh_detection]),
            mock.patch.object(HARMONY_BUILD, "verify_task", side_effect=[env_failure, tasks_outcome, build_outcome]) as verify_mock,
            mock.patch.object(HARMONY_BUILD, "save_cached_detection", return_value={"source": "fresh", "saved": True}),
            mock.patch.object(HARMONY_BUILD.time, "monotonic", side_effect=[100.0, 100.0, 103.0, 104.0, 105.0]),
        ):
            result = HARMONY_BUILD.build_project("/repo", timeout_seconds=10, list_timeout_seconds=10)

        self.assertTrue(result["refreshed_after_failure"])
        self.assertTrue(result["verification"]["success"])
        self.assertEqual(result["verification"]["output"], "")
        self.assertEqual(result["task_list"]["output"], "")
        self.assertEqual([call.args[1] for call in verify_mock.call_args_list], ["tasks", "tasks", "assembleApp"])
        self.assertEqual([call.args[2] for call in verify_mock.call_args_list], [10, 7, 6])
        self.assertEqual([call.kwargs.get("full_output") for call in verify_mock.call_args_list], [True, True, None])

    def test_build_project_build_retry_uses_remaining_deadline(self) -> None:
        cached_detection = {
            "ready": True,
            "repo": {"input": "/repo", "local_path": "/repo", "local_exists": True},
            "resolved": {"sdk_home": "/stale-sdk", "hvigor_path": "/repo/hvigorw"},
            "cache": {"source": "cache"},
        }
        fresh_detection = {
            "ready": True,
            "repo": {"input": "/repo", "local_path": "/repo", "local_exists": True},
            "resolved": {"sdk_home": "/fresh-sdk", "hvigor_path": "/repo/hvigorw"},
            "cache": {"source": "fresh"},
        }
        tasks_outcome = {
            "success": True,
            "exit_code": 0,
            "output": "assembleApp - Assemble the packaged app\n",
            "timed_out": False,
        }
        env_failure = {
            "success": False,
            "exit_code": 1,
            "output": "SDK component missing",
            "timed_out": False,
        }
        build_outcome = {
            "success": True,
            "exit_code": 0,
            "output": "BUILD SUCCESSFUL in 1 s",
            "timed_out": False,
        }

        with (
            mock.patch.object(HARMONY_BUILD, "resolve_verification_detection", side_effect=[cached_detection, fresh_detection]),
            mock.patch.object(HARMONY_BUILD, "verify_task", side_effect=[tasks_outcome, env_failure, build_outcome]) as verify_mock,
            mock.patch.object(HARMONY_BUILD, "save_cached_detection", return_value={"source": "fresh", "saved": True}),
            mock.patch.object(HARMONY_BUILD.time, "monotonic", side_effect=[200.0, 200.0, 201.0, 204.0, 205.0]),
        ):
            result = HARMONY_BUILD.build_project("/repo", timeout_seconds=20, list_timeout_seconds=20)

        self.assertTrue(result["refreshed_after_failure"])
        self.assertTrue(result["verification"]["success"])
        self.assertEqual(result["verification"]["output"], "")
        self.assertEqual(result["task_list"]["output"], "")
        self.assertEqual([call.args[1] for call in verify_mock.call_args_list], ["tasks", "assembleApp", "assembleApp"])
        self.assertEqual([call.args[2] for call in verify_mock.call_args_list], [20, 19, 16])
        self.assertEqual([call.kwargs.get("full_output") for call in verify_mock.call_args_list], [True, None, None])

    def test_verify_task_can_request_full_success_output(self) -> None:
        detection = {
            "ready": True,
            "repo": {"local_path": "/repo"},
            "resolved": {"sdk_home": "/sdk", "hvigor_path": "/repo/hvigorw"},
        }

        with mock.patch.object(
            HARMONY_BUILD,
            "run_hvigor_task",
            return_value={"success": True, "exit_code": 0, "output": "tasks", "timed_out": False},
        ) as run_mock:
            HARMONY_BUILD.verify_task(detection, "tasks", timeout_seconds=12, full_output=True)

        self.assertEqual(run_mock.call_args.kwargs["output_mode"], "full-on-success")

    def test_print_build_result_omits_successful_hvigor_output(self) -> None:
        result = {
            "detection": {
                "repo": {"local_path": "/repo"},
                "resolved": {"sdk_home": "/sdk"},
            },
            "selected_task": "assembleApp",
            "duration_seconds": 2.5,
            "verification": {
                "success": True,
                "exit_code": 0,
                "output": "",
                "timed_out": False,
                "phase": "build",
            },
        }

        with redirect_stdout(io.StringIO()) as output:
            HARMONY_BUILD.print_build_result(result)

        printed = output.getvalue()
        self.assertIn("BUILD SUCCESS", printed)
        self.assertIn("Duration: 2.5s", printed)
        self.assertNotIn("Output:", printed)

    def test_print_build_result_includes_failure_output(self) -> None:
        result = {
            "detection": {
                "repo": {"local_path": "/repo"},
                "resolved": {"sdk_home": "/sdk"},
            },
            "selected_task": "assembleApp",
            "verification": {
                "success": False,
                "exit_code": 1,
                "output": "ArkTS compile error",
                "timed_out": False,
                "phase": "build",
                "duration_seconds": 3.0,
            },
        }

        with redirect_stdout(io.StringIO()) as output:
            HARMONY_BUILD.print_build_result(result)

        printed = output.getvalue()
        self.assertIn("BUILD FAILED", printed)
        self.assertIn("Duration: 3.0s", printed)
        self.assertIn("Output:", printed)
        self.assertIn("ArkTS compile error", printed)

    def test_print_build_result_includes_detection_blockers_when_environment_not_ready(self) -> None:
        result = {
            "detection": {
                "ready": False,
                "repo": {"local_path": "/repo"},
                "resolved": {},
                "blockers": ["sdk_missing", "hvigor_missing_or_not_executable"],
                "blocker_details": {
                    "hvigor_missing_or_not_executable": "Repo wrapper exists but is not executable: /repo/hvigorw",
                },
            },
            "selected_task": "assembleApp",
            "verification": {
                "success": False,
                "exit_code": 1,
                "output": "Environment is not ready for macOS Harmony hvigor verification.",
                "timed_out": False,
                "phase": "build",
            },
        }

        with redirect_stdout(io.StringIO()) as output:
            HARMONY_BUILD.print_build_result(result)

        printed = output.getvalue()
        self.assertIn("Detection blockers: sdk_missing, hvigor_missing_or_not_executable", printed)
        self.assertIn("Repo wrapper exists but is not executable", printed)

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

    def test_run_hvigor_task_full_on_success_reads_complete_output(self) -> None:
        repo_path = Path("/repo")
        hvigor_path = repo_path / "hvigorw"

        def fake_popen(args, **kwargs):
            lines = ["earlyTask - Only visible in the complete task listing"]
            lines.extend(f"tail filler {index}" for index in range(HARMONY_BUILD.HVIGOR_OUTPUT_TAIL_LINES + 5))
            kwargs["stdout"].write("\n".join(lines))
            return mock.Mock(pid=4321, wait=mock.Mock(return_value=0))

        with (
            mock.patch.object(HARMONY_BUILD, "is_executable_file", return_value=True),
            mock.patch.object(HARMONY_BUILD.subprocess, "Popen", side_effect=fake_popen),
        ):
            outcome = HARMONY_BUILD.run_hvigor_task(
                str(repo_path),
                "/sdk/15",
                str(hvigor_path),
                "tasks",
                timeout_seconds=12,
                output_mode="full-on-success",
            )

        self.assertTrue(outcome["success"])
        self.assertIn("earlyTask", outcome["output"])

    def test_run_hvigor_task_full_on_success_keeps_failure_output_tail(self) -> None:
        repo_path = Path("/repo")
        hvigor_path = repo_path / "hvigorw"

        def fake_popen(args, **kwargs):
            lines = ["early diagnostic that should not be returned on failure"]
            lines.extend(f"tail filler {index}" for index in range(HARMONY_BUILD.HVIGOR_OUTPUT_TAIL_LINES + 5))
            lines.append("final failure")
            kwargs["stdout"].write("\n".join(lines))
            return mock.Mock(pid=4321, wait=mock.Mock(return_value=1))

        with (
            mock.patch.object(HARMONY_BUILD, "is_executable_file", return_value=True),
            mock.patch.object(HARMONY_BUILD.subprocess, "Popen", side_effect=fake_popen),
        ):
            outcome = HARMONY_BUILD.run_hvigor_task(
                str(repo_path),
                "/sdk/15",
                str(hvigor_path),
                "tasks",
                timeout_seconds=12,
                output_mode="full-on-success",
            )

        self.assertFalse(outcome["success"])
        self.assertNotIn("early diagnostic", outcome["output"])
        self.assertIn("final failure", outcome["output"])

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

    def test_terminate_process_tree_sends_sigkill_after_sigterm_timeout(self) -> None:
        fake_process = mock.Mock(pid=4321)
        fake_process.wait.side_effect = [
            HARMONY_BUILD.subprocess.TimeoutExpired(cmd=["hvigorw"], timeout=10),
            0,
        ]

        with (
            mock.patch.object(HARMONY_BUILD.os, "name", "posix"),
            mock.patch.object(HARMONY_BUILD.os, "killpg") as killpg_mock,
        ):
            cleanup_message = HARMONY_BUILD.terminate_process_tree(fake_process)

        self.assertIn("SIGKILL", cleanup_message)
        self.assertEqual(
            [call.args for call in killpg_mock.call_args_list],
            [(4321, HARMONY_BUILD.signal.SIGTERM), (4321, HARMONY_BUILD.signal.SIGKILL)],
        )

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

    def test_hvigor_task_rejects_option_like_task_name(self) -> None:
        with (
            redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as error,
        ):
            HARMONY_BUILD.build_parser().parse_args(["verify", "--task=--help"])

        self.assertEqual(error.exception.code, 2)

        with mock.patch.object(HARMONY_BUILD.subprocess, "Popen") as popen_mock:
            outcome = HARMONY_BUILD.run_hvigor_task(
                "/repo",
                "/sdk/15",
                "/repo/hvigorw",
                "--help",
            )

        popen_mock.assert_not_called()
        self.assertFalse(outcome["success"])
        self.assertEqual(outcome["exit_code"], 2)
        self.assertIn("must not start with '-'", outcome["output"])

    def test_run_hvigor_task_non_executable_repo_wrapper_mentions_chmod(self) -> None:
        with mock.patch.object(HARMONY_BUILD, "is_executable_file", return_value=False):
            outcome = HARMONY_BUILD.run_hvigor_task(
                "/repo",
                "/sdk/15",
                "/repo/hvigorw",
                "tasks",
            )

        self.assertFalse(outcome["success"])
        self.assertEqual(outcome["exit_code"], 126)
        self.assertIn("chmod +x hvigorw", outcome["output"])


if __name__ == "__main__":
    unittest.main()
