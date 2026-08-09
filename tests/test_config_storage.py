from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from repoarena.config import initialize, load_config
from repoarena.config.models import (
    AgentConfig,
    EnvironmentAgentConfig,
    RouterAgentConfig,
    SandboxConfig,
)
from repoarena.storage import Database


def test_init_is_idempotent_and_migrates_database(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, capture_output=True)

    paths, created = initialize(repository)
    Database(paths.database).migrate()
    second_paths, second_created = initialize(repository)
    Database(second_paths.database).migrate()

    assert created is True
    assert second_created is False
    config = load_config(paths)
    assert config.schema_version == 1
    assert config.agents.gemini.enabled is False
    assert config.agents.openrouter.base_url == "https://openrouter.ai/api/v1"
    assert config.agents.router.base_url == "http://host.docker.internal:20128/v1"
    ignore = (repository / ".gitignore").read_text(encoding="utf-8")
    assert ignore.count(".repoarena/repoarena.db\n") == 1
    connection = sqlite3.connect(paths.database)
    try:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone() == (2,)
    finally:
        connection.close()


def test_storage_recovers_interrupted_sessions(tmp_path: Path) -> None:
    database = Database(tmp_path / "repoarena.db")
    database.migrate()
    database.upsert_repository("repository", tmp_path, "https://example.test/repo", "main")
    session_id = database.create_session("repository", "task-set", ["fake"])
    agent_id = database.upsert_agent("fake", "test", None)

    with database.connect() as connection:
        connection.execute(
            """INSERT INTO benchmark_tasks(
            id, repository_id, schema_version, base_commit, task_json, verifier_json,
            quality_score, quality_reasons_json, status, created_at, updated_at
            ) VALUES ('task', 'repository', '1', 'base', '{}', '{}', 100, '[]',
            'VALID', 'now', 'now')"""
        )
    run_id = database.create_run(session_id, "task", agent_id)

    assert database.recover_interrupted_sessions("repository") == 1
    with database.connect() as connection:
        session = connection.execute(
            "SELECT status FROM benchmark_sessions WHERE id=?", (session_id,)
        ).fetchone()
        run = connection.execute(
            "SELECT status, error_type FROM benchmark_runs WHERE id=?", (run_id,)
        ).fetchone()
    assert tuple(session) == ("INTERRUPTED",)
    assert tuple(run) == ("AGENT_ERROR", "INTERRUPTED")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: AgentConfig(image="--privileged", executable="codex"),
        lambda: AgentConfig(
            image="repoarena/codex:local",
            executable="codex",
            allowed_domains=["-unsafe.example"],
        ),
        lambda: SandboxConfig(memory="unlimited"),
        lambda: EnvironmentAgentConfig(
            image="repoarena/gemini:local",
            executable="gemini",
            credential_file="credentials.json",
        ),
        lambda: RouterAgentConfig(
            enabled=True,
            image="repoarena/opencode:local",
            executable="opencode",
            provider_id="router",
            base_url="http://router.example.test/v1",
            api_key_env="ROUTER_API_KEY",
            model="coding-model",
            allowed_domains=["router.example.test"],
        ),
        lambda: RouterAgentConfig(
            enabled=True,
            image="repoarena/opencode:local",
            executable="opencode",
            provider_id="router",
            base_url="https://router.example.test:8443/v1",
            api_key_env="ROUTER_API_KEY",
            model="coding-model",
            allowed_domains=["router.example.test"],
        ),
        lambda: RouterAgentConfig(
            enabled=True,
            image="repoarena/opencode:local",
            executable="opencode",
            provider_id="router",
            base_url="https://router.example.test/v1",
            api_key_env="ROUTER_API_KEY",
            allowed_domains=["router.example.test"],
        ),
        lambda: RouterAgentConfig(
            enabled=True,
            image="repoarena/opencode:local",
            executable="opencode",
            provider_id="router",
            base_url="https://router.example.test/v1",
            api_key_env="ROUTER_API_KEY",
            model="coding-model",
            allowed_domains=["different.example.test"],
        ),
    ],
)
def test_unsafe_sandbox_configuration_is_rejected(factory: object) -> None:
    with pytest.raises(ValidationError):
        factory()
