import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "review_scope.py"
SPEC = importlib.util.spec_from_file_location("review_scope", SCRIPT_PATH)
REVIEW_SCOPE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(REVIEW_SCOPE)


class ReviewScopeTests(unittest.TestCase):
    def test_build_summary_detects_dependency_risk_and_test_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "codex@example.com"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Codex"], cwd=repo, check=True, capture_output=True)

            (repo / "src").mkdir()
            (repo / "tests").mkdir()
            (repo / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (repo / "tests" / "test_app.py").write_text("def test_value():\n    assert 1 == 1\n", encoding="utf-8")
            (repo / "package.json").write_text('{"name":"demo","version":"1.0.0"}\n', encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True, capture_output=True)

            (repo / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            (repo / "package.json").write_text('{"name":"demo","version":"1.1.0"}\n', encoding="utf-8")

            changes, scope_source = REVIEW_SCOPE.collect_git_changes(repo, None, None)
            summary = REVIEW_SCOPE.build_summary(repo, changes, scope_source)

        self.assertEqual(summary["scope_source"], "git diff HEAD + untracked")
        self.assertEqual(summary["categories"]["source"], 1)
        self.assertEqual(summary["categories"]["dependencies"], 1)
        self.assertIn("dependencies", summary["risk_tags"])
        self.assertIn("build-toolchain", summary["risk_tags"])
        self.assertTrue(summary["test_gap"])
        hottest_paths = {item["path"] for item in summary["hottest_files"]}
        self.assertIn("package.json", hottest_paths)
        self.assertIn("src/app.py", hottest_paths)

    def test_collect_git_changes_includes_staged_files_before_first_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "codex@example.com"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Codex"], cwd=repo, check=True, capture_output=True)

            (repo / "staged.py").write_text("print('ready')\n", encoding="utf-8")
            subprocess.run(["git", "add", "staged.py"], cwd=repo, check=True, capture_output=True)
            (repo / "notes.md").write_text("# todo\n", encoding="utf-8")

            changes, scope_source = REVIEW_SCOPE.collect_git_changes(repo, None, None)

        self.assertEqual(scope_source, "git diff --cached --root + untracked")
        paths = {item["path"] for item in changes}
        self.assertIn("staged.py", paths)
        self.assertIn("notes.md", paths)

    def test_merge_change_lists_collapses_pure_rename_numstat_into_new_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "codex@example.com"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Codex"], cwd=repo, check=True, capture_output=True)

            (repo / "old.txt").write_text("same content\n", encoding="utf-8")
            subprocess.run(["git", "add", "old.txt"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True, capture_output=True)

            subprocess.run(["git", "mv", "old.txt", "new.txt"], cwd=repo, check=True, capture_output=True)

            changes, _scope_source = REVIEW_SCOPE.collect_git_changes(repo, None, None)

        self.assertEqual([item["path"] for item in changes], ["new.txt"])
        self.assertEqual(changes[0]["additions"], 0)
        self.assertEqual(changes[0]["deletions"], 0)
        self.assertTrue(changes[0]["status"].startswith("R"))

    def test_collect_git_changes_handles_complex_rename_paths_without_double_counting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "codex@example.com"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Codex"], cwd=repo, check=True, capture_output=True)

            (repo / "dir old" / "sub").mkdir(parents=True)
            (repo / "dir old" / "sub" / "file name.txt").write_text("same content\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True, capture_output=True)

            (repo / "dir new" / "sub2").mkdir(parents=True)
            subprocess.run(
                [
                    "git",
                    "mv",
                    "dir old/sub/file name.txt",
                    "dir new/sub2/file new name.txt",
                ],
                cwd=repo,
                check=True,
                capture_output=True,
            )

            changes, _scope_source = REVIEW_SCOPE.collect_git_changes(repo, None, None)

        self.assertEqual([item["path"] for item in changes], ["dir new/sub2/file new name.txt"])
        self.assertEqual(changes[0]["additions"], 0)
        self.assertEqual(changes[0]["deletions"], 0)
        self.assertTrue(changes[0]["status"].startswith("R"))

    def test_prepare_summary_for_output_escapes_non_utf8_paths_without_replacement(self) -> None:
        raw_path = os.fsdecode(b"bad_\xff.txt")
        summary = {
            "repo_path": str(Path("/tmp/repo")),
            "scope_source": "explicit file list",
            "changed_files": [
                {
                    "path": raw_path,
                    "status": "A",
                    "additions": 1,
                    "deletions": 0,
                    "category": "other",
                }
            ],
            "categories": {"other": 1},
            "risk_tags": [],
            "test_gap": False,
            "review_focus": ["focus"],
            "hottest_files": [
                {
                    "path": raw_path,
                    "status": "A",
                    "additions": 1,
                    "deletions": 0,
                }
            ],
        }

        prepared = REVIEW_SCOPE.prepare_summary_for_output(summary)

        self.assertEqual(prepared["changed_files"][0]["path"], r"bad_\xff.txt")
        self.assertEqual(prepared["hottest_files"][0]["path"], r"bad_\xff.txt")
        self.assertNotIn("�", prepared["changed_files"][0]["path"])

    def test_build_summary_marks_deleted_tests_as_test_gap_for_risky_changes(self) -> None:
        changes = [
            {"path": "src/app.py", "status": "M", "additions": 3, "deletions": 1},
            {"path": "tests/test_app.py", "status": "D", "additions": 0, "deletions": 8},
        ]

        summary = REVIEW_SCOPE.build_summary(Path("/tmp/repo"), changes, "explicit file list")

        self.assertTrue(summary["test_gap"])
        self.assertEqual(summary["test_changes"]["deleted"], 1)
        self.assertEqual(summary["test_changes"]["non_deleted"], 0)
        self.assertTrue(any("删除了测试" in item for item in summary["review_focus"]))


if __name__ == "__main__":
    unittest.main()
