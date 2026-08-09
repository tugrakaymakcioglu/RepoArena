# Installation and first benchmark

RepoArena is an alpha source distribution. These instructions keep the CLI, Docker images, provider
credentials, and target repository clearly separated.

## Install the CLI

With uv:

```bash
git clone https://github.com/tugrakaymakcioglu/RepoArena.git
cd RepoArena
uv tool install .
```

With pipx:

```bash
git clone https://github.com/tugrakaymakcioglu/RepoArena.git
cd RepoArena
pipx install .
```

Upgrade a source installation after pulling a newer revision:

```bash
uv tool install --force .
```

## Build runtime images

RepoArena does not publish or silently download provider credentials. Codex, Claude, and Gemini run
in local images containing their official CLIs. OpenRouter and compatible routers use a local
OpenCode image.

macOS/Linux:

```bash
sh ./scripts/build-images.sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-images.ps1
```

For reproducible provider CLI versions:

```bash
CODEX_VERSION=x CLAUDE_VERSION=x GEMINI_VERSION=x OPENCODE_VERSION=x \
  sh ./scripts/build-images.sh
```

```powershell
.\scripts\build-images.ps1 `
  -CodexVersion x -ClaudeVersion x -GeminiVersion x -OpenCodeVersion x
```

These version values are examples known to support the V1 adapter flags. RepoArena resolves and
records the resulting image identity before a benchmark.

## Configure provider-owned authentication

Use a provider API key in the current shell or configure a readable provider-native credential file
path in `.repoarena/config.toml`. Do not paste a key into that file.

macOS/Linux:

```bash
export OPENAI_API_KEY="..."
export ANTHROPIC_API_KEY="..."
export GEMINI_API_KEY="..."
export OPENROUTER_API_KEY="..."
export ROUTER_API_KEY="..."
```

Windows PowerShell:

```powershell
$env:OPENAI_API_KEY = "..."
$env:ANTHROPIC_API_KEY = "..."
$env:GEMINI_API_KEY = "..."
$env:OPENROUTER_API_KEY = "..."
$env:ROUTER_API_KEY = "..."
```

To use a provider-native login or subscription, point RepoArena at the credential file created by
that provider's CLI. Use an absolute host path and forward slashes on Windows:

```toml
[agents.codex]
credential_file = "C:/Users/you/.codex/auth.json"

[agents.claude]
credential_file = "C:/Users/you/.claude/.credentials.json"
```

These are examples; use the actual file selected by your provider installation. RepoArena mounts
only the selected file, read-only, into that agent's solver container and never copies it into the
database, logs, patch artifact, or verifier.

Only credentials for the selected agent are forwarded to its solver container. Verifier containers
receive none of them.

Gemini, OpenRouter, and router profiles are disabled by default. Enable them and select a model in
`.repoarena/config.toml`; see [provider and router configuration](providers.md). Never place the key
itself in TOML.

## Initialize a target repository

Change into the repository being measured—not the RepoArena source directory—then run:

```bash
repoarena init
repoarena doctor
```

`doctor` checks Git, the repository, Docker, runtime images, provider CLI versions, GitHub metadata
access, credentials, and working-tree state. Warnings and errors include an actionable next step.

## Discover and benchmark

```bash
repoarena discover
repoarena benchmark --agent codex
repoarena benchmark --agent claude
repoarena benchmark --agent gemini
repoarena benchmark --agent openrouter
repoarena benchmark --agent router
repoarena report
```

Discovery can be intentionally slow: every accepted task must pass repeated baseline verification.
The HTML report is written to `.repoarena/reports/` in the target repository.

## Troubleshooting

- **No merged PRs found:** verify the `origin` URL and GitHub access with `gh auth status`.
- **Historical commits unavailable:** fetch full history or allow RepoArena to create its private
  mirror under `.repoarena/cache/`.
- **Docker image missing:** rerun the image build script from the RepoArena source checkout.
- **Provider auth missing:** set the matching environment variable or configure a provider-native
  credential file path.
- **Local router unreachable:** use `host.docker.internal`, not `localhost`, in `agents.router.base_url`;
  confirm the configured port and run `repoarena doctor` again.
- **Router model missing:** set the exact model identifier exposed by OpenRouter or your compatible
  router before enabling that adapter.
- **No valid tasks:** inspect discovery rejection counts. Tasks need a clear description, focused
  source changes, changed tests, and a supported reproducible environment.
