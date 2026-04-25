import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "capture_failure.py"
SPEC = importlib.util.spec_from_file_location("capture_failure", SCRIPT_PATH)
CAPTURE_FAILURE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CAPTURE_FAILURE)


class CaptureFailureTests(unittest.TestCase):
    def test_build_report_classifies_missing_python_module_as_dependency_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = CAPTURE_FAILURE.build_report(
                [
                    sys.executable,
                    "-c",
                    "import definitely_missing_module",
                ],
                Path(temp_dir),
                timeout=30,
                line_limit=10,
            )

        self.assertFalse(report["success"])
        self.assertEqual(report["classification"], "dependency")
        self.assertIn("modulenotfounderror", report["signals"])
        self.assertEqual(report["exit_code"], 1)
        self.assertTrue(any("依赖" in step for step in report["next_steps"]))

    def test_build_report_handles_missing_executable_as_environment_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = CAPTURE_FAILURE.build_report(
                ["definitely-not-a-real-command-for-codex"],
                Path(temp_dir),
                timeout=30,
                line_limit=10,
            )

        self.assertFalse(report["success"])
        self.assertEqual(report["classification"], "environment")
        self.assertIn("missing_executable", report["signals"])
        self.assertTrue(report["stderr_tail"])
        self.assertTrue(any("环境" in step or "工作目录" in step for step in report["next_steps"]))

    def test_classify_failure_prefers_build_signal_over_generic_failed_word(self) -> None:
        category, signals = CAPTURE_FAILURE.classify_failure("Build failed\nFailed to execute goal", 1)

        self.assertEqual(category, "build")
        self.assertIn("build failed", signals)

    def test_classify_failure_detects_harmony_arkts_before_hvigor_wrapper(self) -> None:
        category, signals = CAPTURE_FAILURE.classify_failure(
            "hvigor ERROR: ArkTS compiler failed in entry/src/main/ets/pages/Index.ets",
            1,
        )

        self.assertEqual(category, "harmony-arkts")
        self.assertIn("arkts", signals)

    def test_classify_failure_prefers_specific_harmony_roots_over_hvigor_wrapper(self) -> None:
        cases = [
            (
                "hvigor ERROR: DEVECO_SDK_HOME is not set and OpenHarmony SDK API version not found",
                "harmony-deveco-sdk",
                "deveco_sdk_home",
            ),
            (
                "hvigor ERROR: ohpm install failed while resolving oh-package.json5",
                "harmony-ohpm",
                "ohpm",
            ),
            (
                "hvigor ERROR: hdc install failed: no connected device",
                "harmony-hdc",
                "no connected device",
            ),
        ]

        for output, expected_category, expected_signal in cases:
            with self.subTest(expected_category=expected_category):
                category, signals = CAPTURE_FAILURE.classify_failure(output, 1)

                self.assertEqual(category, expected_category)
                self.assertIn(expected_signal, signals)

    def test_classify_failure_detects_java_jdk_mismatch(self) -> None:
        category, signals = CAPTURE_FAILURE.classify_failure(
            "Execution failed for task ':compileJava'. invalid source release: 21",
            1,
        )

        self.assertEqual(category, "java-jdk-mismatch")
        self.assertIn("invalid source release", signals)

    def test_classify_failure_prefers_specific_spring_roots_over_context_wrapper(self) -> None:
        cases = [
            (
                "Failed to load ApplicationContext: UnsatisfiedDependencyException: "
                "No qualifying bean of type 'UserService'",
                "java-bean",
                "no qualifying bean",
            ),
            (
                "Failed to load ApplicationContext: Could not resolve placeholder 'db.url' "
                "in application.yml",
                "java-profile-config",
                "could not resolve placeholder",
            ),
            (
                "Application run failed: Flyway migration checksum mismatch in schema migration",
                "java-migration",
                "flyway",
            ),
            (
                "Application run failed: dependency resolution failed due to duplicate class",
                "java-dependency-conflict",
                "dependency resolution failed",
            ),
        ]

        for output, expected_category, expected_signal in cases:
            with self.subTest(expected_category=expected_category):
                details = CAPTURE_FAILURE.classify_failure_details(output, 1)

                self.assertEqual(details["classification"], expected_category)
                self.assertIn(expected_signal, details["signals"])
                self.assertTrue(
                    any(
                        match["classification"] == "java-spring-context"
                        for match in details["secondary_matches"]
                    )
                )

    def test_classify_failure_detects_java_bean_issue_without_context_wrapper(self) -> None:
        category, signals = CAPTURE_FAILURE.classify_failure(
            "UnsatisfiedDependencyException: No qualifying bean of type 'UserRepository'",
            1,
        )

        self.assertEqual(category, "java-bean")
        self.assertIn("no qualifying bean", signals)

    def test_classify_failure_detects_react_hydration_issue(self) -> None:
        category, signals = CAPTURE_FAILURE.classify_failure(
            "Hydration failed because the initial UI does not match server-rendered HTML.",
            1,
        )

        self.assertEqual(category, "react-hydration")
        self.assertIn("hydration failed", signals)

    def test_classify_failure_detects_playwright_timeout_before_network_timeout(self) -> None:
        category, signals = CAPTURE_FAILURE.classify_failure(
            "TimeoutError: locator.click: Timeout 30000ms exceeded while waiting for selector",
            1,
        )

        self.assertEqual(category, "react-playwright-timeout")
        self.assertIn("timeouterror:", signals)

    def test_classify_failure_does_not_treat_generic_timeout_error_as_playwright(self) -> None:
        cases = [
            "TimeoutError: database query timed out while reading users table",
            "TimeoutError: API request timeout after 30s from upstream gateway",
        ]

        for output in cases:
            with self.subTest(output=output):
                category, signals = CAPTURE_FAILURE.classify_failure(output, 1)

                self.assertEqual(category, "network")
                self.assertNotIn("timeouterror:", signals)

    def test_classify_failure_prefers_resource_module_over_arkts_wrapper(self) -> None:
        details = CAPTURE_FAILURE.classify_failure_details(
            "hvigor ERROR: ArkTS compiler wrapper failed while parsing module.json5: "
            "JSON5 parse error, invalid resource reference",
            1,
        )

        self.assertEqual(details["classification"], "harmony-resource-module")
        self.assertIn("module.json5", details["signals"])
        secondary_categories = {match["classification"] for match in details["secondary_matches"]}
        self.assertIn("harmony-arkts", secondary_categories)
        self.assertIn("harmony-hvigor", secondary_categories)

    def test_classify_failure_treats_bare_vite_econnrefused_as_network(self) -> None:
        category, signals = CAPTURE_FAILURE.classify_failure(
            "VITE_API_URL=http://127.0.0.1:5173 request failed with ECONNREFUSED",
            1,
        )

        self.assertEqual(category, "network")
        self.assertIn("econnrefused", signals)

    def test_classify_failure_treats_vite_build_context_as_react_build(self) -> None:
        details = CAPTURE_FAILURE.classify_failure_details(
            "Vite build failed: failed to load config from vite.config.ts",
            1,
        )

        self.assertEqual(details["classification"], "react-build")
        self.assertIn("vite", details["signals"])

    def test_build_report_classifies_timeout_without_output_as_command_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = CAPTURE_FAILURE.build_report(
                [
                    sys.executable,
                    "-c",
                    "import time; time.sleep(2)",
                ],
                Path(temp_dir),
                timeout=1,
                line_limit=10,
            )

        self.assertFalse(report["success"])
        self.assertTrue(report["timed_out"])
        self.assertEqual(report["classification"], "command-timeout")
        self.assertIn("timeout_expired_no_output", report["signals"])
        self.assertTrue(any("卡住" in step or "超时" in step for step in report["next_steps"]))

    def test_build_report_preserves_secondary_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = CAPTURE_FAILURE.build_report(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        "sys.stderr.write('Failed to load ApplicationContext: "
                        "No qualifying bean of type UserService'); "
                        "sys.exit(1)"
                    ),
                ],
                Path(temp_dir),
                timeout=30,
                line_limit=10,
            )

        self.assertEqual(report["classification"], "java-bean")
        self.assertIn("secondary_matches", report)
        self.assertTrue(
            any(match["classification"] == "java-spring-context" for match in report["secondary_matches"])
        )

    def test_cli_preserves_original_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--cwd",
                    temp_dir,
                    "--",
                    sys.executable,
                    "-c",
                    "import sys; sys.exit(7)",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

        self.assertEqual(result.returncode, 7)
        self.assertIn("退出码：7", result.stdout)


if __name__ == "__main__":
    unittest.main()
