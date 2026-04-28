# DocsHub Content Publishing

Use this when adding or updating content in a DocsHub repository.

## Scope

- Treat the repo as a documentation snapshot plus `docsets.json`.
- Do not require application build or unit-test workflows unless the content repo actually defines them.
- Keep source URLs and provenance near the Markdown content when available.

## Validation

- Parse `docsets.json` with a JSON parser.
- Confirm new `docsets[].root` values point under `docs/`.
- Run `git diff --check`.
- Search candidate files for obvious secrets, tokens, `.env`, local credentials, and accidental diagnostic logs.
- If searchability is part of the request, rebuild or refresh the affected docset and run `lookup` for a representative query.

## Git Boundary

- Inspect untracked files before staging.
- Stage only content, index configuration, and intentional metadata.
- Exclude system files, local logs, caches, and temporary exports.
