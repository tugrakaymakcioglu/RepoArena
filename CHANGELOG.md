# Changelog

All notable changes to RepoArena are documented here. The project follows semantic versioning while
it remains alpha software.

## 0.1.1 - 2026-08-09

### Added

- Gemini CLI adapter using user-owned `GEMINI_API_KEY` credentials.
- OpenRouter and generic OpenAI-compatible router adapters powered by OpenCode headless mode.
- First-class 9Router host connectivity through `host.docker.internal`.
- Dedicated provider/router configuration and security documentation.

### Fixed

- `repoarena doctor` no longer reports missing images or credentials for disabled agents.
- Provider API-key values no longer appear in Docker command arguments.
- Secret-in-patch detection now covers the active agent's configured credential dynamically.
- Agent home directories are writable ephemeral tmpfs mounts while container roots stay read-only.
- Local-router hostname resolution works on Docker engines that support `host-gateway`.
- ANSI terminal control sequences are removed before diagnostics enter local storage or reports.
