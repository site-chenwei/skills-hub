# Skill Repository Lifecycle Checklist

## Active And Archive Inventory

- Enumerate active directories under `skills/` that contain `SKILL.md`.
- Enumerate archived directories under `archive/skills/` that contain `SKILL.md`.
- Each active repo-owned skill should have `SKILL.md` and `agents/openai.yaml`.
- Add `run.py` and tests when an active skill has deterministic helper behavior.
- Keep detailed workflows in `references/` when active `SKILL.md` would become too large.
- Treat a skill present in both `skills/` and `archive/skills/` as an attention item.
- Treat an archived skill that is still installed as a hygiene risk; report it instead of syncing it as active.

## User-Level AGENTS Boundary

- Keep global AGENTS focused on language, safety, minimal changes, validation integrity, Git safety, and communication.
- Move domain workflows into active skills only when GSD or global rules do not already cover them. Keep archived structured development, verification, code review, and Git delivery material as historical reference unless explicitly revived.
- For external config files, confirm the real path and edit only that file.

## Source Validation

- Prefer `python3 -m unittest skills.test_all_skills` for this repository.
- Use `python3 -m unittest discover -s skills -p 'test_*.py'` only as a discovery cross-check.
- Treat root-level `python3 -m unittest discover` returning zero tests as non-evidence.

## Runtime Install Sync

- Sync only active repo-owned skill folders.
- Exclude `__pycache__/`, `*.pyc`, and `.pytest_cache/`.
- Use directory-level `rsync -a --delete` so removed files do not linger.
- After syncing, run `diff -qr` and installation-state smoke commands.
- Treat an active repo-owned source skill that is missing under the install root as an attention item, not as implicit success.
- Do not reinstall archived skills during normal parity work.
