---
name: grill-with-gsd
description: "Use when inserting grill-me before a GSD plan phase to clarify requirements or design, then persist confirmed grill-me decisions into the phase CONTEXT.md and a structured GRILL.md evidence file without modifying GSD runtime."
---

# Grill With GSD

Use this skill as a thin adapter between GSD phase planning and the `grill-me` skill. It does not create a new questioning framework and does not modify GSD itself.

## Scope

- Supports only GSD phase `CONTEXT.md` files under `.planning/phases/`.
- Runs before `$gsd-plan-phase <phase>` when the phase context needs hard clarification.
- Calls `grill-me` as the questioning engine.
- Writes confirmed conclusions back to `CONTEXT.md`, so later GSD sessions and agents can consume them normally.
- Writes a structured `<phase>-GRILL.md` evidence file for traceability.
- Does not commit, push, sync installed copies, or automatically run `$gsd-plan-phase`.

## Target Resolution

Supported invocations:

```text
$grill-with-gsd
$grill-with-gsd phase 09
$grill-with-gsd .planning/phases/09-theme/09-CONTEXT.md
```

First resolve the target context with the bundled helper:

```bash
python3 <skill_root>/run.py locate-context --repo <repo> [target...] --format json
```

Use the current working directory as `<repo>` unless the user provides another repo. If the helper is unavailable, fall back to a manual search under `.planning/phases/`. If the target cannot be resolved to exactly one GSD `CONTEXT.md`, fail loud and show candidates; do not guess.

Before editing, run `git status --porcelain` in the repo. If the target `CONTEXT.md` is already dirty, tell the user that this run will append to the existing file and will not overwrite prior content. Dirty unrelated files do not block the skill.

## Grill-Me Handoff

Load the `grill-me` skill and use it directly. If `grill-me` is unavailable, stop and report that this adapter cannot run.

Do not invent a fixed questionnaire. Prepare the source material for `grill-me` from the phase directory:

- target `CONTEXT.md`
- matching `DISCUSSION-LOG.md`
- matching `RESEARCH.md`
- matching `VALIDATION.md`
- existing `UI-SPEC.md` or `PLAN.md` files if present
- current GSD state files if they are cheap to read

Tell `grill-me` the plan/design to interrogate and add these hard constraints:

- Ask one question at a time.
- Provide a recommended answer for each question.
- If an answer can be found by exploring local files, explore instead of asking.
- Do not write files during the questioning phase.
- Finish by producing `Final Grill Decisions` and `Question Trail` blocks in the formats below.

## Required Final Confirmation

After `grill-me` finishes, show the proposed `Final Grill Decisions` to the user once. Only write files after the user confirms. If the user rejects the summary, continue grilling or stop without writing.

## Context Write Format

Append a new run to `CONTEXT.md`; do not overwrite or rewrite old grill decisions.

```md
## Grill-Me Clarifications

### Run YYYY-MM-DD HH:mm

Status: passed | partial | blocked
Evidence: <phase>-GRILL.md

#### Decisions
- D-GRILL-YYYYMMDD-01: ...

#### Scope Cuts
- OUT-GRILL-YYYYMMDD-01: ...

#### Assumptions
- A-GRILL-YYYYMMDD-01: ...

#### Acceptance Updates
- AC-GRILL-YYYYMMDD-01: ...

#### Remaining Open Questions
- none

#### Plan Blockers
- none
```

If a new decision supersedes an older one, append a new item that explicitly says `Supersedes D-GRILL-...`; do not delete the older item.

## Evidence File Format

Write or append to `<phase>-GRILL.md` in the same phase directory. Use structured summary, not a verbatim transcript.

```md
# Grill-Me Review

## Run YYYY-MM-DD HH:mm

Status: passed | partial | blocked
Context file: <phase>-CONTEXT.md
Trigger: plan-before-clarification

## Question Trail

### Q1: ...
Recommended answer: ...
User answer: ...
Decision: ...
Impact on CONTEXT.md: D-GRILL-YYYYMMDD-01

## Final Grill Decisions
...
```

## Status Semantics

- `passed`: no plan-blocking ambiguity remains; suggest `$gsd-plan-phase <phase>` as the next step.
- `partial`: no blocker remains, but open questions exist; write them under `Remaining Open Questions` and tell the user the planner must include validation or checkpoints for them.
- `blocked`: blocker remains; write `Plan Blockers`, write evidence, and do not recommend running `$gsd-plan-phase`.

## Failure Rules

Fail loud and do not claim success when:

- no unique target `CONTEXT.md` can be resolved
- the target file is not a GSD phase context
- `grill-me` cannot be loaded
- the user has not confirmed the final decision block
- writing `CONTEXT.md` or `<phase>-GRILL.md` fails
- the result is `blocked`

For `blocked`, file writes are allowed after confirmation so the blocker is preserved, but the final response must say not to proceed to plan.

## Final Response

Keep the close-out short:

- status: `passed`, `partial`, or `blocked`
- updated files
- whether `$gsd-plan-phase <phase>` is recommended
- any open questions or blockers that affect planning
