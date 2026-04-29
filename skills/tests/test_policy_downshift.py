import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills"

SKILL_NAMES = [
    "docs-hub",
    "harmony-build",
    "skill-repo-lifecycle",
]


def read_skill(name: str) -> str:
    return (SKILL_ROOT / name / "SKILL.md").read_text(encoding="utf-8")


def read_agent_metadata(name: str) -> str:
    return (SKILL_ROOT / name / "agents" / "openai.yaml").read_text(encoding="utf-8")


class PolicyDownshiftTests(unittest.TestCase):
    def test_runtime_path_policy_is_present_in_every_skill(self) -> None:
        for name in SKILL_NAMES:
            with self.subTest(skill=name):
                text = read_skill(name)
                self.assertTrue(
                    "实际打开的 `SKILL.md`" in text or "actually opened `SKILL.md`" in text,
                    f"{name} must derive skill root from the opened entry file",
                )
                self.assertTrue(
                    "显式确认目标存在" in text or "confirm they exist" in text,
                    f"{name} must check bundled attachments before use",
                )
                self.assertTrue(
                    "附件缺失" in text or "missing attachment" in text,
                    f"{name} must report missing attachments instead of guessing paths",
                )

    def test_agent_metadata_repeats_attachment_check(self) -> None:
        for name in SKILL_NAMES:
            with self.subTest(skill=name):
                text = read_agent_metadata(name)
                self.assertIn("only from the opened SKILL.md path", text)
                self.assertTrue("exist" in text or "exists" in text)

    def test_security_and_validation_rules_are_downshifted_to_active_skills(self) -> None:
        harmony = read_skill("harmony-build")
        self.assertIn("HdsNavigation", harmony)
        self.assertIn("源码级检查不足以覆盖风险", harmony)

        docs = read_skill("docs-hub")
        self.assertIn("do not silently degrade", docs)
        self.assertIn("fabricated sources", docs)

        lifecycle = read_skill("skill-repo-lifecycle")
        self.assertIn("skills.test_all_skills", lifecycle)
        self.assertIn("/Users/bill/.cc-switch/skills", lifecycle)

    def test_reference_extensions_cover_active_history_driven_gaps(self) -> None:
        docs = read_skill("docs-hub")

        self.assertIn("references/content-publishing.md", docs)


if __name__ == "__main__":
    unittest.main()
