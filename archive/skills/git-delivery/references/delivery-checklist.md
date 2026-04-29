# Git Delivery Checklist

Use this checklist when the delivery request is broader than a single obvious commit.

## Before Staging

- Run `git status --short --branch` and inspect all tracked and untracked paths.
- Prefer `run.py preflight --repo <repo>` and `run.py stage-plan --repo <repo>` for a read-only delivery gate and staging recommendation.
- Identify generated or local-only files before staging: `.DS_Store`, crash logs, HiLog snapshots, appfreeze files, build outputs, caches, temporary exports, and local IDE metadata.
- Treat `.env`, private keys, certificates, credentials, token dumps, and real test accounts as blockers.
- If a previous Git command was interrupted, re-run status and upstream checks from scratch.
- `stage-plan` must not modify the index; use it only to produce an auditable explicit file list.

## Before Commit

- Run `git diff --check`.
- If staged files exist, run `git diff --cached --check`.
- Prefer `run.py commit-plan --repo <repo>` after staging to inspect staged files, diffstat, and commit-message suggestions.
- Run the smallest validation that can support the delivery claim.
- Confirm generated side effects are either intended or removed before commit.

## Before Push

- Confirm branch name and upstream.
- Use `git rev-list --left-right --count HEAD...@{u}` when an upstream exists.
- Do not push to a guessed remote or branch.

## After Push

- Re-run `git status --short --branch`.
- Confirm ahead/behind is `0 0` or explain why not.
- Prefer `run.py post-push-check --repo <repo> --expected-branch <branch> --expected-commit <commit>` when a push actually happened.
- Report commit id, branch, validation commands, and any intentionally untracked local artifacts.
