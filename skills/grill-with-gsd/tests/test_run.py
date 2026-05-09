from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


RUN_PATH = Path(__file__).resolve().parents[1] / "run.py"
SKILL_PATH = Path(__file__).resolve().parents[1] / "SKILL.md"
AGENT_PATH = Path(__file__).resolve().parents[1] / "agents" / "openai.yaml"
SPEC = importlib.util.spec_from_file_location("grill_with_gsd_run", RUN_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RunTests(unittest.TestCase):
    def test_help_returns_zero(self) -> None:
        self.assertEqual(MODULE.main(["--help"]), 0)

    def test_unknown_command_returns_usage_error(self) -> None:
        self.assertEqual(MODULE.main(["unknown"]), 2)

    def test_skill_finalizes_without_confirmation_and_delivers_git(self) -> None:
        skill_text = SKILL_PATH.read_text(encoding="utf-8")
        agent_text = AGENT_PATH.read_text(encoding="utf-8")

        self.assertIn("## Autonomous Finalization", skill_text)
        self.assertIn("Do not ask for final confirmation", skill_text)
        self.assertIn("## Automatic Git Delivery", skill_text)
        self.assertIn("git commit", skill_text)
        self.assertIn("git push", skill_text)
        self.assertNotIn("## Required Final Confirmation", skill_text)
        self.assertNotIn("the user has not confirmed the final decision block", skill_text)
        self.assertIn("without final confirmation", agent_text)
        self.assertIn("commit and push", agent_text)


if __name__ == "__main__":
    unittest.main()
