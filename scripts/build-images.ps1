param(
    [string]$CodexVersion = "latest",
    [string]$ClaudeVersion = "latest"
)

$ErrorActionPreference = "Stop"
$repoArenaRoot = Split-Path -Parent $PSScriptRoot

& docker build -t repoarena/egress-proxy:local -f "$repoArenaRoot/docker/sandbox/proxy.Dockerfile" $repoArenaRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to build the RepoArena egress proxy image." }

& docker build --build-arg "CODEX_VERSION=$CodexVersion" -t repoarena/codex:local -f "$repoArenaRoot/docker/agents/codex.Dockerfile" $repoArenaRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to build the RepoArena Codex image." }

& docker build --build-arg "CLAUDE_VERSION=$ClaudeVersion" -t repoarena/claude:local -f "$repoArenaRoot/docker/agents/claude.Dockerfile" $repoArenaRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to build the RepoArena Claude image." }

Write-Host "RepoArena Docker images are ready." -ForegroundColor Green
