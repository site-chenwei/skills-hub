import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills"

SKILL_NAMES = [
    "code-review-checklist",
    "docs-hub",
    "git-delivery",
    "harmony-build",
    "project-onboarding",
    "skill-repo-lifecycle",
    "structured-dev",
    "verification-and-debug",
]


def read_skill(name: str) -> str:
    return (SKILL_ROOT / name / "SKILL.md").read_text(encoding="utf-8")


def read_agent_metadata(name: str) -> str:
    return (SKILL_ROOT / name / "agents" / "openai.yaml").read_text(encoding="utf-8")


def read_reference(name: str, reference: str) -> str:
    return (SKILL_ROOT / name / "references" / reference).read_text(encoding="utf-8")


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

    def test_security_and_validation_rules_are_downshifted_to_target_skills(self) -> None:
        verification = read_skill("verification-and-debug")
        self.assertIn("API Key", verification)
        self.assertIn("`.env`", verification)
        self.assertIn("伪造成功", verification)

        structured = read_skill("structured-dev")
        self.assertIn("静态检查、单测、脚本回归或手工最小路径", structured)
        self.assertIn("不因项目类型或“补验证”机械触发编译", structured)
        self.assertIn("HdsNavigation", structured)

        review = read_skill("code-review-checklist")
        self.assertIn("凭据泄露", review)
        self.assertIn("破坏性 Git", review)

        harmony = read_skill("harmony-build")
        self.assertIn("HdsNavigation", harmony)
        self.assertIn("源码级检查不足以覆盖风险", harmony)

        onboarding = read_skill("project-onboarding")
        self.assertIn("不读取或展示敏感值", onboarding)

        docs = read_skill("docs-hub")
        self.assertIn("do not silently degrade", docs)
        self.assertIn("fabricated sources", docs)

        git_delivery = read_skill("git-delivery")
        self.assertIn("git diff --check", git_delivery)
        self.assertIn("凭据", git_delivery)

        lifecycle = read_skill("skill-repo-lifecycle")
        self.assertIn("skills.test_all_skills", lifecycle)
        self.assertIn("/Users/bill/.cc-switch/skills", lifecycle)

    def test_reference_extensions_cover_history_driven_gaps(self) -> None:
        structured = read_skill("structured-dev")
        docs = read_skill("docs-hub")

        self.assertIn("references/reference-porting.md", structured)
        self.assertIn("references/content-publishing.md", docs)

    def test_skill_composition_covers_delivery_and_lifecycle(self) -> None:
        composition = read_reference("structured-dev", "skill-composition.md")
        structured_metadata = read_agent_metadata("structured-dev")

        self.assertIn("`git-delivery`", composition)
        self.assertIn("`skill-repo-lifecycle`", composition)
        self.assertIn("$git-delivery", structured_metadata)
        self.assertIn("$skill-repo-lifecycle", structured_metadata)


if __name__ == "__main__":
    unittest.main()
