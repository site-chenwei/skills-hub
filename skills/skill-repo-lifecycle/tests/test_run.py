from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


RUN_PATH = Path(__file__).resolve().parents[1] / "run.py"
SPEC = importlib.util.spec_from_file_location("skill_lifecycle_run", RUN_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RunTests(unittest.TestCase):
    def test_help_returns_zero(self) -> None:
        self.assertEqual(MODULE.main(["--help"]), 0)

    def test_unknown_command_returns_usage_error(self) -> None:
        self.assertEqual(MODULE.main(["unknown"]), 2)


if __name__ == "__main__":
    unittest.main()
