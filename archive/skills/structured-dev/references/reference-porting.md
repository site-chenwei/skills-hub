# Reference Porting

Use this when the user asks to follow an upstream implementation, copy a proven algorithm, or align a local feature with a reference project.

## When To Apply

- The user names an upstream project, source file, paper, spec, or existing local reference implementation.
- The request is about architecture, hot paths, algorithms, data structures, formats, or performance behavior.
- The user rejects conceptual similarity and wants implementation boundaries to match the reference.

## Workflow

1. Establish the reference baseline.
   - Prefer local docs or checked-in reference packages first when they exist.
   - If the reference is external and current facts matter, use the official upstream source.
   - Record exact version, tag, file, function, or document section.
2. Separate names from behavior.
   - Identify the upstream data model, conversion/loading path, runtime hot path, indexing/matching strategy, persistence format, error path, and validation path.
   - Do not claim alignment because local names resemble upstream names.
3. Compare local implementation.
   - List what matches, what intentionally differs, and what is missing.
   - For performance work, follow object allocation, repeated parsing, I/O boundaries, cache behavior, and runtime lookup complexity.
4. Define the porting boundary.
   - State whether the task is a full port, partial adaptation, compatibility layer, or reference-informed redesign.
   - Remove non-required legacy behavior when the user has explicitly said compatibility is unnecessary.
5. Implement the smallest coherent migration.
   - Keep source-detail tracing, debug views, and provenance side channels off the hot path unless required.
   - Avoid mixing unrelated compatibility, UI, storage, and performance changes in one unreviewable patch.
6. Validate against the reference.
   - Add focused tests for equivalence, tie-break rules, parser/format boundaries, and large-input behavior.
   - For runtime-sensitive changes, validate the real user path, not only build or cold start.

## Output

- Reference baseline:
- Local gap:
- Chosen boundary:
- Files and hot paths:
- Validation:
- Known differences:
