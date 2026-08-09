#!/usr/bin/env sh
set -eu

repoarena_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
codex_version=${CODEX_VERSION:-latest}
claude_version=${CLAUDE_VERSION:-latest}

docker build -t repoarena/egress-proxy:local -f "$repoarena_root/docker/sandbox/proxy.Dockerfile" "$repoarena_root"
docker build --build-arg "CODEX_VERSION=$codex_version" -t repoarena/codex:local -f "$repoarena_root/docker/agents/codex.Dockerfile" "$repoarena_root"
docker build --build-arg "CLAUDE_VERSION=$claude_version" -t repoarena/claude:local -f "$repoarena_root/docker/agents/claude.Dockerfile" "$repoarena_root"

printf '%s\n' "RepoArena Docker images are ready."
