import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills"

SKILL_NAMES = [
    "docs-hub",
    "harmony-build",
    "skill-repo-lifecycle",
]


class SkillContractTests(unittest.TestCase):
    def test_expected_skill_directories_are_present(self) -> None:
        discovered = sorted(path.name for path in SKILL_ROOT.iterdir() if (path / "SKILL.md").exists())

        self.assertEqual(SKILL_NAMES, discovered)

    def test_skill_metadata_and_agent_prompt_names_match(self) -> None:
        for name in SKILL_NAMES:
            with self.subTest(skill=name):
                skill_dir = SKILL_ROOT / name
                skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
                agent_text = (skill_dir / "agents" / "openai.yaml").read_text(encoding="utf-8")

                self.assertIn(f"name: {name}", skill_text)
                self.assertIn("description:", skill_text)
                self.assertIn(f'display_name: "{name}"', agent_text)
                self.assertIn(f"Use ${name}", agent_text)

    def test_frontmatter_description_is_yaml_safe(self) -> None:
        for name in SKILL_NAMES:
            with self.subTest(skill=name):
                skill_text = (SKILL_ROOT / name / "SKILL.md").read_text(encoding="utf-8")
                frontmatter = skill_text.split("---", 2)[1]
                description_line = next(line for line in frontmatter.splitlines() if line.startswith("description:"))
                description_value = description_line.split(":", 1)[1].strip()

                if ": " in description_value:
                    self.assertTrue(
                        description_value.startswith(('"', "'")),
                        "description values containing ': ' must be quoted for YAML frontmatter parsers",
                    )

    def test_run_py_help_and_unknown_command_contract(self) -> None:
        for name in SKILL_NAMES:
            with self.subTest(skill=name):
                runner = SKILL_ROOT / name / "run.py"
                help_proc = subprocess.run(
                    [sys.executable, str(runner), "--help"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                unknown_proc = subprocess.run(
                    [sys.executable, str(runner), "__contract_unknown_command__"],
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(help_proc.returncode, 0, help_proc.stderr)
                self.assertIn("usage:", help_proc.stderr + help_proc.stdout)
                self.assertEqual(unknown_proc.returncode, 2, unknown_proc.stderr + unknown_proc.stdout)
                self.assertIn("unknown command:", unknown_proc.stderr + unknown_proc.stdout)


if __name__ == "__main__":
    unittest.main()
