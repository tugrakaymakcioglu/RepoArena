from __future__ import annotations

from repoarena.agents.base import AgentRunner
from repoarena.agents.claude import ClaudeAgentRunner
from repoarena.agents.codex import CodexAgentRunner
from repoarena.agents.gemini import GeminiAgentRunner
from repoarena.agents.router import OpenCodeRouterAgent
from repoarena.config.models import RepoArenaConfig
from repoarena.exceptions import ConfigurationError
from repoarena.sandbox import DockerRunner


def configured_agents(config: RepoArenaConfig, docker: DockerRunner) -> dict[str, AgentRunner]:
    agents: dict[str, AgentRunner] = {}
    if config.agents.codex.enabled:
        agents["codex"] = CodexAgentRunner(config.agents.codex, docker)
    if config.agents.claude.enabled:
        agents["claude"] = ClaudeAgentRunner(config.agents.claude, docker)
    if config.agents.gemini.enabled:
        agents["gemini"] = GeminiAgentRunner(config.agents.gemini, docker)
    if config.agents.openrouter.enabled:
        agents["openrouter"] = OpenCodeRouterAgent("openrouter", config.agents.openrouter, docker)
    if config.agents.router.enabled:
        agents["router"] = OpenCodeRouterAgent("router", config.agents.router, docker)
    return agents


def select_agents(
    config: RepoArenaConfig,
    docker: DockerRunner,
    *,
    agent: str | None,
    all_agents: bool,
) -> list[AgentRunner]:
    available = configured_agents(config, docker)
    if all_agents:
        return list(available.values())
    if agent is None:
        raise ConfigurationError("An agent name is required when --all is not used")
    if agent not in available:
        raise ConfigurationError(f"Agent is unknown or disabled: {agent}")
    return [available[agent]]
