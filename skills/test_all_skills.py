from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parent


def iter_test_paths() -> list[Path]:
    paths = set(SKILLS_ROOT.glob("*/tests/test_*.py"))
    paths.update((SKILLS_ROOT / "tests").glob("test_*.py"))
    return sorted(paths)


def load_tests(loader: unittest.TestLoader, _standard_tests: unittest.TestSuite, _pattern: str | None) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    suite.addTests(_standard_tests)
    for path in iter_test_paths():
        module_name = f"skills_hub_{path.parent.parent.name.replace('-', '_')}_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        suite.addTests(loader.loadTestsFromModule(module))
    return suite


class AggregateDiscoveryTests(unittest.TestCase):
    def test_shared_skill_tests_are_discovered(self) -> None:
        shared_test = SKILLS_ROOT / "tests" / "test_policy_downshift.py"

        self.assertIn(shared_test, iter_test_paths())


if __name__ == "__main__":
    unittest.main()
