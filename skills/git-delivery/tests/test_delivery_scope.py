from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "delivery_scope.py"
SPEC = importlib.util.spec_from_file_location("git_delivery_scope", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DeliveryScopeTests(unittest.TestCase):
    def test_path_flags_identify_local_artifacts_and_secret_risks(self) -> None:
        self.assertIn("system-artifact", MODULE.path_flags(".DS_Store"))
        self.assertIn("diagnostic-artifact", MODULE.path_flags("logs/appfreeze-site.txt"))
        self.assertIn("secret-risk", MODULE.path_flags(".env.local"))
        self.assertIn("generated-artifact", MODULE.path_flags("core/BuildProfile.ets"))

    def test_collect_summary_reports_dirty_repo_attention(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            (repo / "src.txt").write_text("hello\n", encoding="utf-8")
            (repo / ".DS_Store").write_text("local\n", encoding="utf-8")
            (repo / ".env.local").write_text("TOKEN=value\n", encoding="utf-8")

            summary = MODULE.collect_summary(repo)

        self.assertTrue(summary["ok"])
        self.assertFalse(summary["status_clean"])
        flags = {flag for item in summary["attention"] for flag in item.get("flags", [])}
        self.assertIn("system-artifact", flags)
        self.assertIn("secret-risk", flags)

    def test_collect_summary_checks_staged_diff_hygiene(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            (repo / "bad.txt").write_text("bad trailing whitespace  \n", encoding="utf-8")
            subprocess.run(["git", "add", "bad.txt"], cwd=repo, check=True, capture_output=True)

            summary = MODULE.collect_summary(repo)

        self.assertFalse(summary["checks"]["git_diff_cached_check"]["ok"])
        self.assertTrue(summary["checks"]["git_diff_cached_check"]["output"])
        flags = {flag for item in summary["attention"] for flag in item.get("flags", [])}
        self.assertIn("diff-cached-check-failed", flags)

    def test_preflight_splits_blockers_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            (repo / ".DS_Store").write_text("local\n", encoding="utf-8")
            (repo / ".env.local").write_text("TOKEN=value\n", encoding="utf-8")

            preflight = MODULE.build_preflight(MODULE.collect_summary(repo))

        self.assertFalse(preflight["ok"])
        self.assertTrue(any(item["id"] == "secret-risk" for item in preflight["blockers"]))
        self.assertTrue(any(item["id"] == "system-artifact" for item in preflight["warnings"]))

    def test_stage_plan_is_read_only_and_classifies_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            (repo / "tracked.txt").write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True, capture_output=True)
            (repo / "tracked.txt").write_text("new\n", encoding="utf-8")
            (repo / "notes.log").write_text("diagnostic\n", encoding="utf-8")

            before = subprocess.run(["git", "status", "--short"], cwd=repo, check=True, capture_output=True, text=True).stdout
            plan = MODULE.build_stage_plan(MODULE.collect_summary(repo))
            after = subprocess.run(["git", "status", "--short"], cwd=repo, check=True, capture_output=True, text=True).stdout

        self.assertEqual(before, after)
        actions = {item["path"]: item["recommended_action"] for item in plan["files"]}
        self.assertEqual("stage", actions["tracked.txt"])
        self.assertEqual("exclude", actions["notes.log"])

    def test_commit_plan_requires_staged_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

            plan = MODULE.build_commit_plan(MODULE.collect_summary(repo))

        self.assertFalse(plan["ok"])
        self.assertTrue(any(item["id"] == "no-staged-changes" for item in plan["blockers"]))

    def test_blocked_planning_mode_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--mode",
                    "commit-plan",
                    "--repo",
                    str(repo),
                    "--format",
                    "json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(1, result.returncode)
        self.assertFalse(payload["ok"])
        self.assertTrue(any(item["id"] == "no-staged-changes" for item in payload["blockers"]))

    def test_commit_plan_suggests_message_for_staged_skill_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            skill_file = repo / "skills" / "git-delivery" / "SKILL.md"
            skill_file.parent.mkdir(parents=True)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            skill_file.write_text("demo\n", encoding="utf-8")
            subprocess.run(["git", "add", str(skill_file.relative_to(repo))], cwd=repo, check=True, capture_output=True)

            plan = MODULE.build_commit_plan(MODULE.collect_summary(repo))

        self.assertTrue(plan["ok"])
        self.assertEqual("更新 git-delivery 交付能力", plan["suggested_message"])
        self.assertEqual(["skills/git-delivery/SKILL.md"], plan["staged_files"])

    def test_post_push_check_blocks_missing_upstream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

            check = MODULE.build_post_push_check(
                MODULE.collect_summary(repo),
                expected_branch=None,
                expected_commit=None,
            )

        self.assertFalse(check["ok"])
        self.assertTrue(any(item["id"] == "upstream-missing" for item in check["blockers"]))

    def test_post_push_check_warns_when_synced_worktree_is_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            remote = root / "remote.git"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True)
            (repo / "tracked.txt").write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True, capture_output=True)
            (repo / "tracked.txt").write_text("new\n", encoding="utf-8")

            check = MODULE.build_post_push_check(
                MODULE.collect_summary(repo),
                expected_branch="main",
                expected_commit="HEAD",
            )

        self.assertTrue(check["ok"])
        self.assertTrue(check["synced"])
        self.assertTrue(any(item["id"] == "worktree-dirty" for item in check["warnings"]))


if __name__ == "__main__":
    unittest.main()
