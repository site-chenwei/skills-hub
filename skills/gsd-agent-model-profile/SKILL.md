---
name: gsd-agent-model-profile
description: Use when configuring GSD custom sub-agent model profiles, restoring GSD agent model settings after updates overwrite ~/.codex/agents files, or when the user mentions ~/.codex/agents, model_reasoning_effort, gpt-5.5, medium, high, or xhigh reasoning tiers for GSD agents.
---

# GSD Agent Model Profile

Use this skill to apply or verify the standard model profile for GSD custom sub-agents.

## What it does

- Writes `model = "gpt-5.5"` into each targeted GSD standalone agent TOML file.
- Writes `model_reasoning_effort` according to the fixed quality/cost balance policy.
- Defaults to `$CODEX_HOME/agents`; if `CODEX_HOME` is unset, uses `~/.codex/agents`.
- Supports a custom agents directory for fixtures or non-default installs.
- Supports `--agent <name>` to target one GSD agent only; with `--agent`, optional `--model` and `--effort` override that one file's target profile.

Do not write these fields into the global `config.toml` `[agents.<name>]` registry block. That registry should only register the agent and point at its `config_file`; model configuration belongs in the standalone agent file, for example:

```toml
model = "gpt-5.5"
model_reasoning_effort = "xhigh"
```

Run this once after each GSD update or any operation that may replace files under `~/.codex/agents`.

## Commands

Set `<skill_root>` to the directory containing this `SKILL.md`, then confirm `scripts/apply-gsd-agent-model-profile.sh` exists under that root.

Apply to the default agents directory:

```bash
<skill_root>/scripts/apply-gsd-agent-model-profile.sh
```

Preview changes without writing:

```bash
<skill_root>/scripts/apply-gsd-agent-model-profile.sh --dry-run
```

Verify the current profile:

```bash
<skill_root>/scripts/apply-gsd-agent-model-profile.sh --verify
```

Use a fixture or custom agents directory:

```bash
<skill_root>/scripts/apply-gsd-agent-model-profile.sh --dry-run --agents-dir /tmp/gsd-agents-fixture
<skill_root>/scripts/apply-gsd-agent-model-profile.sh --agents-dir /tmp/gsd-agents-fixture
<skill_root>/scripts/apply-gsd-agent-model-profile.sh --verify --agents-dir /tmp/gsd-agents-fixture
```

Target one agent only:

```bash
<skill_root>/scripts/apply-gsd-agent-model-profile.sh --agent gsd-code-reviewer
<skill_root>/scripts/apply-gsd-agent-model-profile.sh --verify --agent gsd-code-reviewer
<skill_root>/scripts/apply-gsd-agent-model-profile.sh --agent gsd-codebase-mapper --model gpt-5.5 --effort high
```

The repo runner exposes the same workflow:

```bash
python3 <skill_root>/run.py dry-run --agents-dir /tmp/gsd-agents-fixture
python3 <skill_root>/run.py apply --agents-dir /tmp/gsd-agents-fixture
python3 <skill_root>/run.py verify --agents-dir /tmp/gsd-agents-fixture
python3 <skill_root>/run.py apply --agent gsd-code-reviewer
```

## Reasoning Effort Policy

`xhigh`:

- `gsd-assumptions-analyzer`
- `gsd-code-reviewer`
- `gsd-planner`
- `gsd-plan-checker`
- `gsd-roadmapper`
- `gsd-verifier`
- `gsd-security-auditor`
- `gsd-integration-checker`
- `gsd-eval-planner`

`high`:

- `gsd-advisor-researcher`
- `gsd-ai-researcher`
- `gsd-code-fixer`
- `gsd-debug-session-manager`
- `gsd-debugger`
- `gsd-doc-synthesizer`
- `gsd-doc-verifier`
- `gsd-doc-writer`
- `gsd-domain-researcher`
- `gsd-eval-auditor`
- `gsd-executor`
- `gsd-framework-selector`
- `gsd-nyquist-auditor`
- `gsd-phase-researcher`
- `gsd-project-researcher`
- `gsd-research-synthesizer`
- `gsd-ui-auditor`
- `gsd-ui-checker`
- `gsd-ui-researcher`
- `gsd-user-profiler`

`medium`:

- `gsd-codebase-mapper`
- `gsd-doc-classifier`
- `gsd-intel-updater`
- `gsd-pattern-mapper`
