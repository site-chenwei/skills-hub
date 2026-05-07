from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "gsd_context.py"
SPEC = importlib.util.spec_from_file_location("grill_with_gsd_context", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_context(repo: Path, phase: str, name: str) -> Path:
    phase_dir = repo / ".planning" / "phases" / f"{phase}-{name}"
    phase_dir.mkdir(parents=True)
    context = phase_dir / f"{phase}-CONTEXT.md"
    context.write_text(f"# Phase {phase}\n", encoding="utf-8")
    return context


class GsdContextTests(unittest.TestCase):
    def test_resolves_explicit_context_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            context = write_context(repo, "09", "theme")

            payload = MODULE.resolve(repo, [str(context.relative_to(repo))])

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["context_file"], ".planning/phases/09-theme/09-CONTEXT.md")
        self.assertEqual(payload["phase"], "09")

    def test_resolves_phase_number(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            write_context(repo, "09", "theme")
            write_context(repo, "10", "ux")

            payload = MODULE.resolve(repo, ["phase", "9"])

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["context_file"], ".planning/phases/09-theme/09-CONTEXT.md")

    def test_resolves_single_context_without_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            write_context(repo, "02", "schema")

            payload = MODULE.resolve(repo, [])

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reason"], "single-context")

    def test_uses_state_phase_when_multiple_candidates_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            write_context(repo, "02", "schema")
            write_context(repo, "03", "runtime")
            state = repo / ".planning" / "STATE.md"
            state.write_text("Current focus: Phase 3 - runtime\n", encoding="utf-8")

            payload = MODULE.resolve(repo, [])

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reason"], "state-current-phase")
        self.assertEqual(payload["phase"], "03")

    def test_reports_ambiguous_contexts_without_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            write_context(repo, "02", "schema")
            write_context(repo, "03", "runtime")

            payload = MODULE.resolve(repo, [])

        self.assertFalse(payload["ok"])
        self.assertIn("multiple", payload["error"])
        self.assertEqual(len(payload["candidates"]), 2)

    def test_rejects_non_gsd_context_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            outside = repo / "09-CONTEXT.md"
            outside.write_text("# not phase context\n", encoding="utf-8")

            payload = MODULE.resolve(repo, [str(outside.relative_to(repo))])

        self.assertFalse(payload["ok"])
        self.assertIn("not a GSD phase CONTEXT.md", payload["error"])


if __name__ == "__main__":
    unittest.main()
