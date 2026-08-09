# RepoArena

**SWE-bench for your own repository.**

Benchmark AI coding agents on the issues, pull requests, and tests that shaped your codebase—not
on someone else's benchmark.

[![CI](https://img.shields.io/github/actions/workflow/status/tugrakaymakcioglu/RepoArena/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/tugrakaymakcioglu/RepoArena/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-0B7285?style=flat-square)](LICENSE)
[![Status: Alpha](https://img.shields.io/badge/Status-Alpha-F59E0B?style=flat-square)](#project-status)
[![Telemetry: None](https://img.shields.io/badge/Telemetry-None-16A34A?style=flat-square)](#privacy-by-default)

Generic coding benchmarks can tell you which agent performs well on a shared task set. RepoArena
answers the question that matters for your team:

> **Which AI coding agent actually performs best on this repository?**

RepoArena reconstructs real historical tasks at their pre-fix commits, gives every agent the same
sanitized problem, and independently verifies each generated patch in Docker. Results come from
executed tests. RepoArena never inserts demo scores or estimated costs.

```text
Historical Issue
      │
      ▼
Historical Base Commit
      │
      ├───────────────┐
      ▼               ▼
    Codex           Claude
      │               │
      ▼               ▼
   Patch A           Patch B
      │               │
      └───────┬───────┘
              ▼
        Hidden Verifier
              │
              ▼
         Local Report
```

## Why RepoArena

| Generic benchmark | RepoArena |
| --- | --- |
| Measures performance on public benchmark tasks | Measures performance on your repository's history |
| Uses benchmark-wide language and framework distributions | Preserves your stack, conventions, and test suite |
| May expose known solutions in public history | Gives solvers a synthetic one-commit repository |
| Produces a general leaderboard | Produces a repository-specific, reproducible comparison |

RepoArena concentrates engineering effort on the difficult part: creating trustworthy tasks from
software history without leaking the human solution.

## What you get

- **Repository-specific tasks** from merged GitHub pull requests, linked issues, source changes,
  test changes, and CI evidence.
- **Quality gates** that reject documentation-only, formatting-only, dependency-only, generated,
  oversized, unclear, or unverifiable candidates.
- **Baseline validation** that requires the historical base to fail reproducibly and the human
  source change to pass the same hidden tests reproducibly.
- **Leakage-resistant reconstruction** using `git archive` and a fresh synthetic repository with no
  remote, tags, reflog, branches, or future Git objects.
- **Independent Docker verification** with fresh workspaces, bounded resources, no credentials,
  and networking disabled for final tests.
- **Fair agent comparison** across immutable task definitions and identical verifier logic.
- **Local SQLite history** plus terminal and self-contained HTML reports.
- **Extensible adapters** for Codex CLI, Claude Code, and future coding agents.

## Install

RepoArena is currently distributed from source while the project is in alpha.

### Requirements

- Python 3.12 or newer
- Git
- a reachable Linux Docker daemon
- [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/)
- GitHub CLI authentication, `GITHUB_TOKEN`, or a public GitHub repository
- your own Codex and/or Claude credentials for real agent runs

### 1. Install the CLI

```bash
git clone https://github.com/tugrakaymakcioglu/RepoArena.git
cd RepoArena
uv tool install .
```

Using pipx instead:

```bash
pipx install .
```

### 2. Build the isolated runtime images

macOS/Linux:

```bash
sh ./scripts/build-images.sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-images.ps1
```

The scripts build local proxy, Codex, and Claude images. You can pin provider CLI versions for a
repeatable build; see [the installation guide](docs/installation.md).

### 3. Benchmark your repository

```bash
cd /path/to/your-project

repoarena init
repoarena doctor
repoarena discover
repoarena benchmark --agent codex
repoarena benchmark --agent claude
repoarena report
```

Use `repoarena benchmark --all` to snapshot one task set and run every enabled agent sequentially.

## How it works

1. **Discover** — Read GitHub and Git history without changing the active checkout.
2. **Score** — Keep only focused changes with strong task, source, test, CI, and reproducibility
   signals.
3. **Validate** — Prove twice that the historical base fails and the human source change passes.
4. **Reconstruct** — Export the base into a one-commit repository that contains no future history.
5. **Solve** — Run the selected agent in a resource-bounded Docker environment.
6. **Verify** — Apply only its patch to an independent base, restore hidden tests, and test with the
   network disabled.
7. **Report** — Store exact results locally and compare agents only on identical completed task
   sets.

The solver receives an opaque task ID, a sanitized description, and detected languages. It does not
receive the original repository URL, issue or PR number, historical commit IDs, human patch, hidden
tests, verifier commands, or expected outputs.

## Supported workflows

| Area | Alpha support |
| --- | --- |
| Repository metadata | GitHub via authenticated `gh`, optional `GITHUB_TOKEN`, or public REST API |
| Agents | Codex CLI and Claude Code in locally built Docker images |
| Verification profiles | Python/pytest, Node test scripts, Go tests, or an explicit custom image |
| Persistence | Local SQLite with transactional schema migrations |
| Reports | Rich terminal summary and escaped, self-contained HTML |
| Provider tests | Opt-in only; normal CI makes no paid API calls |

## Privacy by default

> **Your repository and benchmark results stay on your machine.**

RepoArena has no account, telemetry, analytics, hosted database, model gateway, or RepoArena cloud
backend. It never ships with shared provider keys and never pays for user inference.

The coding agent you select may send task text or repository code to its own provider. RepoArena's
provider-only network restricts solver egress, but provider traffic is still remote processing under
that provider's terms. The verifier receives no agent credentials and final verification has no
network access.

Read the full [threat model](docs/security.md) before using private or untrusted repositories.

## Configuration

`repoarena init` creates `.repoarena/config.toml` and local runtime directories. The configuration
contains no secret values; credentials come from environment variables or explicitly selected
provider-native files.

```toml
[benchmark]
quality_threshold = 70
timeout_seconds = 900
baseline_repetitions = 2

[sandbox]
engine = "docker"
solver_network = "provider-only"
setup_network = "bridge"

[agents.codex]
enabled = true

[agents.claude]
enabled = true
```

Valid agent patches are retained under the ignored `.repoarena/runs/` directory. The database,
caches, reports, and run artifacts are also ignored automatically. Do not place API keys in
`config.toml`.

## Documentation

- [Installation and first benchmark](docs/installation.md)
- [Architecture](docs/architecture.md)
- [Benchmark task format](docs/task-format.md)
- [Threat model](docs/security.md)
- [Repository publishing metadata](docs/repository-metadata.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Support](SUPPORT.md)

## Development

```bash
uv sync --locked --all-extras
uv run pytest -m "not provider"
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv build
```

The deterministic fake-agent suite covers successful, wrong, no-change, malformed, flaky,
subprocess-failure, leakage, sandbox, verifier, storage, and report paths. Docker-marked tests run a
real provider-free verifier flow when Docker is available. Real-provider calls are never required
for CI.

## Project status

RepoArena is **alpha software**. The core local vertical slice, Codex and Claude adapters, Docker
isolation, and local reports are implemented; compatibility across diverse repository build systems
will continue to improve.

Current limitations:

- GitHub is the only remote metadata provider.
- High-quality discovery currently requires a merged change with separable source and test patches.
- Automatic verifier profiles cover Python, Node, and Go; unusual builds need explicit commands and
  a Docker image.
- Binary and submodule patches are rejected in V1.
- Provider images are built locally rather than published by RepoArena.
- Provider endpoint allowlists may need updates when vendor authentication endpoints change.

The roadmap includes broader extraction, deeper GitHub integration, optional shared benchmark
history, and task-specific recommendations. There is no SaaS, hosted worker, account system, or
model router in V1.

## Contributing

Issues and pull requests are welcome. Security-sensitive changes to discovery, historical
reconstruction, patches, or sandboxing must include deterministic regression tests and a short
leakage/threat analysis. Start with [CONTRIBUTING.md](CONTRIBUTING.md).

Please use [GitHub Security Advisories](https://github.com/tugrakaymakcioglu/RepoArena/security/advisories/new)
for private vulnerability reports rather than public issues.

## License

RepoArena is licensed under [Apache-2.0](LICENSE).
