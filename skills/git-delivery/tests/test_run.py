from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


RUN_PATH = Path(__file__).resolve().parents[1] / "run.py"
AGENT_METADATA_PATH = Path(__file__).resolve().parents[1] / "agents" / "openai.yaml"
SPEC = importlib.util.spec_from_file_location("git_delivery_run", RUN_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RunTests(unittest.TestCase):
    def test_help_returns_zero(self) -> None:
        self.assertEqual(MODULE.main(["--help"]), 0)

    def test_unknown_command_returns_usage_error(self) -> None:
        self.assertEqual(MODULE.main(["unknown"]), 2)

    def test_planning_commands_are_registered(self) -> None:
        for command in ("preflight", "stage-plan", "commit-plan", "post-push-check"):
            with self.subTest(command=command):
                self.assertIn(command, MODULE.COMMANDS)

    def test_agent_metadata_uses_declared_skill_name(self) -> None:
        text = AGENT_METADATA_PATH.read_text(encoding="utf-8")

        self.assertIn("Use $git-delivery", text)
        self.assertNotIn("Use -delivery", text)


if __name__ == "__main__":
    unittest.main()
