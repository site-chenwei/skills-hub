import filecmp
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_ROOT / "scripts" / "apply-gsd-agent-model-profile.sh"
RUNNER_PATH = SKILL_ROOT / "run.py"

XHIGH_AGENTS = [
    "gsd-assumptions-analyzer",
    "gsd-planner",
    "gsd-plan-checker",
    "gsd-roadmapper",
    "gsd-verifier",
    "gsd-security-auditor",
    "gsd-integration-checker",
    "gsd-eval-planner",
]
HIGH_AGENTS = [
    "gsd-advisor-researcher",
    "gsd-ai-researcher",
    "gsd-code-fixer",
    "gsd-code-reviewer",
    "gsd-debug-session-manager",
    "gsd-debugger",
    "gsd-doc-synthesizer",
    "gsd-doc-verifier",
    "gsd-doc-writer",
    "gsd-domain-researcher",
    "gsd-eval-auditor",
    "gsd-executor",
    "gsd-framework-selector",
    "gsd-nyquist-auditor",
    "gsd-phase-researcher",
    "gsd-project-researcher",
    "gsd-research-synthesizer",
    "gsd-ui-auditor",
    "gsd-ui-checker",
    "gsd-ui-researcher",
    "gsd-user-profiler",
]
MEDIUM_AGENTS = [
    "gsd-codebase-mapper",
    "gsd-doc-classifier",
    "gsd-intel-updater",
    "gsd-pattern-mapper",
]
EXPECTED_EFFORT = {
    **{name: "xhigh" for name in XHIGH_AGENTS},
    **{name: "high" for name in HIGH_AGENTS},
    **{name: "medium" for name in MEDIUM_AGENTS},
}


def create_fixture(directory: Path) -> None:
    for name in EXPECTED_EFFORT:
        (directory / f"{name}.toml").write_text(
            "\n".join(
                [
                    f'name = "{name}"',
                    f'description = "{name} description"',
                    'sandbox_mode = "workspace-write"',
                    "developer_instructions = '''",
                    'model = "do-not-touch-inside-developer-instructions"',
                    'model_reasoning_effort = "do-not-touch-inside-developer-instructions"',
                    "'''",
                    "",
                ]
            ),
            encoding="utf-8",
        )


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


class ApplyGsdAgentModelProfileTests(unittest.TestCase):
    def test_dry_run_does_not_modify_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            agents_dir = Path(raw_dir)
            create_fixture(agents_dir)
            before = {path.name: path.read_text(encoding="utf-8") for path in agents_dir.glob("*.toml")}

            proc = run_script("--dry-run", "--agents-dir", str(agents_dir))

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("WOULD_UPDATE", proc.stdout)
            after = {path.name: path.read_text(encoding="utf-8") for path in agents_dir.glob("*.toml")}
            self.assertEqual(before, after)

    def test_apply_verify_and_idempotence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir, tempfile.TemporaryDirectory() as snapshot_parent:
            agents_dir = Path(raw_dir)
            snapshot_dir = Path(snapshot_parent) / "snapshot"
            create_fixture(agents_dir)

            apply_proc = run_script("--agents-dir", str(agents_dir))
            self.assertEqual(apply_proc.returncode, 0, apply_proc.stderr)
            self.assertIn("UPDATED", apply_proc.stdout)

            for name, effort in EXPECTED_EFFORT.items():
                text = (agents_dir / f"{name}.toml").read_text(encoding="utf-8")
                self.assertTrue(text.startswith(f'model = "gpt-5.5"\nmodel_reasoning_effort = "{effort}"\n'))
                self.assertIn('model = "do-not-touch-inside-developer-instructions"', text)
                self.assertIn('model_reasoning_effort = "do-not-touch-inside-developer-instructions"', text)
                self.assertIn('sandbox_mode = "workspace-write"', text)
                self.assertIn(f'description = "{name} description"', text)

            verify_proc = run_script("--verify", "--agents-dir", str(agents_dir))
            self.assertEqual(verify_proc.returncode, 0, verify_proc.stderr)
            self.assertIn("failed=0", verify_proc.stdout)

            shutil.copytree(agents_dir, snapshot_dir)
            second_apply_proc = run_script("--agents-dir", str(agents_dir))
            self.assertEqual(second_apply_proc.returncode, 0, second_apply_proc.stderr)
            self.assertFalse(filecmp.dircmp(agents_dir, snapshot_dir).diff_files)

    def test_missing_agent_reports_error_but_keeps_processing(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            agents_dir = Path(raw_dir)
            create_fixture(agents_dir)
            missing_path = agents_dir / "gsd-planner.toml"
            missing_path.unlink()

            proc = run_script("--dry-run", "--agents-dir", str(agents_dir))

            self.assertEqual(proc.returncode, 1)
            self.assertIn(str(missing_path), proc.stderr)
            self.assertIn("WOULD_UPDATE", proc.stdout)

    def test_runner_dispatches_profile_commands(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            agents_dir = Path(raw_dir)
            create_fixture(agents_dir)

            proc = subprocess.run(
                ["python3", str(RUNNER_PATH), "dry-run", "--agents-dir", str(agents_dir)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("WOULD_UPDATE", proc.stdout)


if __name__ == "__main__":
    unittest.main()
