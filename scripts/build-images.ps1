param(
    [string]$CodexVersion = "latest",
    [string]$ClaudeVersion = "latest",
    [string]$GeminiVersion = "latest",
    [string]$OpenCodeVersion = "latest"
)

$ErrorActionPreference = "Stop"
$repoArenaRoot = Split-Path -Parent $PSScriptRoot

& docker build -t repoarena/egress-proxy:local -f "$repoArenaRoot/docker/sandbox/proxy.Dockerfile" $repoArenaRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to build the RepoArena egress proxy image." }

& docker build --build-arg "CODEX_VERSION=$CodexVersion" -t repoarena/codex:local -f "$repoArenaRoot/docker/agents/codex.Dockerfile" $repoArenaRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to build the RepoArena Codex image." }

& docker build --build-arg "CLAUDE_VERSION=$ClaudeVersion" -t repoarena/claude:local -f "$repoArenaRoot/docker/agents/claude.Dockerfile" $repoArenaRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to build the RepoArena Claude image." }

& docker build --build-arg "GEMINI_VERSION=$GeminiVersion" -t repoarena/gemini:local -f "$repoArenaRoot/docker/agents/gemini.Dockerfile" $repoArenaRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to build the RepoArena Gemini image." }

& docker build --build-arg "OPENCODE_VERSION=$OpenCodeVersion" -t repoarena/opencode:local -f "$repoArenaRoot/docker/agents/opencode.Dockerfile" $repoArenaRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to build the RepoArena OpenCode image." }

Write-Host "RepoArena Docker images are ready." -ForegroundColor Green
