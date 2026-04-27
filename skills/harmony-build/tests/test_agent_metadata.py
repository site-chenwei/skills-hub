from __future__ import annotations

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
    def test_default_prompt_describes_macos_first_verification(self) -> None:
        prompt = read_default_prompt(AGENT_FILE)

        self.assertIsNotNone(prompt)
        assert prompt is not None
        self.assertIn(
            "macOS HarmonyOS/OpenHarmony development environment",
            prompt,
        )
        self.assertIn(
            "Reuse cached ready baselines",
            prompt,
        )
        self.assertIn(
            "supports detect --timeout-seconds",
            prompt,
        )
        self.assertIn(
            "parse complete successful tasks output",
            prompt,
        )
        self.assertIn(
            "Do not pass internal .hvigor task keys such as :entry:default@CompileArkTS",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
