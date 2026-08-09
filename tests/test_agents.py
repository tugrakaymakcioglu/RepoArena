from __future__ import annotations

from repoarena.agents.claude import ClaudeAgentRunner
from repoarena.agents.codex import CodexAgentRunner
from repoarena.benchmark.models import SolverTaskV1
from repoarena.config.models import AgentConfig, SandboxConfig
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
