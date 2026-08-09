# Contributing to RepoArena

RepoArena's correctness boundary is task construction and independent verification. Changes that
touch discovery, historical reconstruction, patches, or sandboxes should include a deterministic
regression test and should describe the leakage/security consequences.

## Before you start

- Use the issue forms for bugs and feature proposals.
- Keep changes focused; do not combine unrelated refactors with security-sensitive behavior.
- Never use a private repository, real provider transcript, or live credential as a fixture.
- Discuss architectural changes before investing in a large implementation.

## Development setup

```bash
python -m pip install uv
uv sync --all-extras
uv run pre-commit install
```

Before opening a pull request, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -m "not provider"
uv build
```

Do not add provider keys, private repository content, recorded provider sessions, or real benchmark
databases to fixtures. Provider integration tests must use the `provider` marker and remain opt-in.

## Pull requests

Explain the user-visible result first, then the implementation. For changes to discovery,
reconstruction, sandboxing, or verification, include:

1. the invariant being protected;
2. a deterministic regression test;
3. any remaining limitation or residual risk;
4. evidence from lint, typing, tests, and package build.

All subprocess calls must use argument arrays. Benchmark code must never reset, clean, checkout, or
otherwise mutate the user's active working copy.

## Provider adapters

Keep provider-specific command construction and metadata parsing inside the adapter. The shared
orchestrator must remain provider-neutral. Provider tests must be explicitly marked `provider`, use
the contributor's own credentials, and never run in normal CI.
