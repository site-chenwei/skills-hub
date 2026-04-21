import unittest
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[2]


def read_display_name(agent_file: Path) -> str | None:
    for raw_line in agent_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("display_name:"):
            continue
        _, value = line.split(":", 1)
        return value.strip().strip('"').strip("'")
    return None


class AgentMetadataTests(unittest.TestCase):
    def test_display_name_matches_skill_directory_name(self) -> None:
        for agent_file in sorted(SKILLS_ROOT.glob("*/agents/openai.yaml")):
            skill_name = agent_file.parents[1].name
            display_name = read_display_name(agent_file)
            self.assertEqual(display_name, skill_name, str(agent_file))


if __name__ == "__main__":
    unittest.main()
