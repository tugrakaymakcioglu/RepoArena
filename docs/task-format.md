# Benchmark task format

The V1 schema has three deliberate views.

## Internal task

`BenchmarkTaskV1` contains repository identity, base/gold commits, original references, quality
metadata, and a private verifier specification. It is local controller data and must not cross into
the solver container.

## Solver task

`SolverTaskV1` contains only:

- `schema_version`
- a deterministic but opaque task ID
- a sanitized natural-language task description
- detected languages

It excludes repository URLs, issue/PR numbers, historical SHAs, gold-derived file paths, hidden test
names, verification commands, and expected outcomes.

## Verifier specification

`VerifierSpecV1` contains the pinned execution recipe, hidden test patch, human non-test patch used
only for baseline validation, protected paths, and repetition count. It is never mounted into or
serialized for the solver.

Schema additions must remain backward-readable. Breaking field semantics require a new
`schema_version` and migration.
