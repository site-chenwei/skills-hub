from __future__ import annotations

import importlib.util
import subprocess
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


if __name__ == "__main__":
    unittest.main()
