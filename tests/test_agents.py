from __future__ import annotations

import json

from repoarena.agents.claude import ClaudeAgentRunner
from repoarena.agents.codex import CodexAgentRunner
from repoarena.agents.gemini import GeminiAgentRunner
from repoarena.agents.registry import configured_agents
from repoarena.agents.router import OpenCodeRouterAgent
from repoarena.benchmark.models import SolverTaskV1
from repoarena.config.models import (
    AgentConfig,
    RepoArenaConfig,
    RouterAgentConfig,
    SandboxConfig,
)
from repoarena.sandbox import DockerRunner


def test_provider_commands_are_noninteractive_and_ephemeral() -> None:
    docker = DockerRunner(SandboxConfig())
    codex = CodexAgentRunner(AgentConfig(image="codex", executable="codex"), docker)
    claude = ClaudeAgentRunner(AgentConfig(image="claude", executable="claude"), docker)

    assert codex.command() == [
        "codex",
        "exec",
        "--cd",
        "/workspace",
        "--ephemeral",
        "--json",
        "--color",
        "never",
        "--sandbox",
        "workspace-write",
        "-",
    ]
    assert "--no-session-persistence" in claude.command()
    assert "--bare" in claude.command()


def test_gemini_command_is_headless_and_auto_approves_workspace_tools() -> None:
    docker = DockerRunner(SandboxConfig())
    gemini = GeminiAgentRunner(
        AgentConfig(image="gemini", executable="gemini", model="gemini-model"), docker
    )

    assert gemini.command() == [
        "gemini",
        "--yolo",
        "--skip-trust",
        "--output-format",
        "stream-json",
        "--model",
        "gemini-model",
    ]
    assert gemini.additional_environment() == {"GEMINI_CLI_TRUST_WORKSPACE": "true"}


def test_router_uses_inline_non_secret_opencode_configuration(monkeypatch: object) -> None:
    secret = "router-" + "secret-value"
    monkeypatch.setenv("CUSTOM_ROUTER_KEY", secret)
    config = RouterAgentConfig(
        enabled=True,
        image="opencode",
        executable="opencode",
        model="vendor/coding-model",
        provider_id="custom",
        base_url="https://router.example.test/v1",
        api_key_env="CUSTOM_ROUTER_KEY",
        allowed_domains=["router.example.test"],
    )
    router = OpenCodeRouterAgent("router", config, DockerRunner(SandboxConfig()))

    environment = router.additional_environment()
    inline = json.loads(environment["OPENCODE_CONFIG_CONTENT"])

    assert router.command() == [
        "opencode",
        "--pure",
        "run",
        "--format",
        "json",
        "--model",
        "custom/vendor/coding-model",
        "Follow the complete task supplied through standard input.",
    ]
    assert secret not in environment["OPENCODE_CONFIG_CONTENT"]
    assert inline["provider"]["custom"]["options"]["apiKey"] == "{env:CUSTOM_ROUTER_KEY}"
    assert inline["provider"]["custom"]["models"]["vendor/coding-model"]["tool_call"] is True
    assert inline["share"] == "disabled"
    assert inline["permission"]["external_directory"] == "deny"
    assert router.secret_values() == (secret,)


def test_registry_exposes_only_enabled_agents() -> None:
    config = RepoArenaConfig()
    config.agents.codex.enabled = False
    config.agents.claude.enabled = False
    config.agents.gemini.enabled = True
    docker = DockerRunner(config.sandbox)

    assert list(configured_agents(config, docker)) == ["gemini"]


def test_solver_prompt_contains_no_private_metadata() -> None:
    task = SolverTaskV1(
        id="opaque-id",
        task_description="Correct arithmetic behavior without changing the public interface.",
        languages=["Python"],
    )
    prompt = CodexAgentRunner.prompt(task)

    assert "opaque-id" in prompt
    assert "github.com" not in prompt
    assert "base_commit" not in prompt
    assert "verification" not in prompt


def test_exact_provider_metadata_is_parsed_without_estimation() -> None:
    output = '{"type":"result","model":"provider-model","total_cost_usd":0.125}\n'

    assert CodexAgentRunner.extract_model(output) == "provider-model"
    assert CodexAgentRunner.extract_exact_cost(output) == 0.125
    assert CodexAgentRunner.extract_exact_cost('{"tokens": 500}') is None
