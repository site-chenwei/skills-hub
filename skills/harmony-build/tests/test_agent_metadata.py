import unittest
from pathlib import Path


AGENT_FILE = Path(__file__).resolve().parents[1] / "agents" / "openai.yaml"


def read_default_prompt(agent_file: Path) -> str | None:
    for raw_line in agent_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("default_prompt:"):
            continue
        _, value = line.split(":", 1)
        return value.strip().strip('"').strip("'")
    return None


class HarmonyBuildAgentMetadataTests(unittest.TestCase):
    def test_default_prompt_runs_build_directly_when_verification_is_needed(self) -> None:
        prompt = read_default_prompt(AGENT_FILE)

        self.assertIsNotNone(prompt)
        assert prompt is not None
        self.assertIn(
            "when build verification is needed run the chosen public hvigor task directly instead of inserting verify --task tasks first",
            prompt,
        )
        self.assertIn(
            "Use verify --task tasks only when the user explicitly asks for task listing or when you are troubleshooting hvigor or environment drift",
            prompt,
        )
        self.assertIn(
            "Do not pass internal .hvigor task keys such as :entry:default@CompileArkTS",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
