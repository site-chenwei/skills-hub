import importlib.util
import unittest
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parent


def load_tests(loader: unittest.TestLoader, _standard_tests: unittest.TestSuite, _pattern: str | None) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for path in sorted(SKILLS_ROOT.glob("*/tests/test_*.py")):
        module_name = f"skills_hub_{path.parent.parent.name.replace('-', '_')}_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        suite.addTests(loader.loadTestsFromModule(module))
    return suite


if __name__ == "__main__":
    unittest.main()
