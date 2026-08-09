from __future__ import annotations

from pathlib import Path

import pytest
from test_vertical_slice import make_task

from repoarena.agents.fake import FakeAgentRunner
from repoarena.benchmark.models import CommandSpec, RunStatus
from repoarena.benchmark.orchestrator import BenchmarkOrchestrator
from repoarena.benchmark.workspace import PatchValidator
from repoarena.config import RepoArenaPaths
from repoarena.config.models import NetworkPolicy, RepoArenaConfig
from repoarena.sandbox import DockerRunner
from repoarena.storage import Database
from repoarena.verification.verifier import Verifier


def _docker_or_skip() -> DockerRunner:
    runner = DockerRunner(RepoArenaConfig().sandbox)
    if not runner.daemon_ready():
        pytest.skip("Docker daemon is unavailable")
    return runner


@pytest.mark.docker
def test_real_docker_verifier_completes_fake_agent_vertical_slice(
    synthetic_repository: object,
) -> None:
    fixture = synthetic_repository
    docker = _docker_or_skip()
    image = "python:3.12-slim"
    if not docker.image_exists(image):
        docker.pull_image(image)
    paths = RepoArenaPaths.for_repository(fixture.path)
    for directory in (paths.state, paths.tasks, paths.runs, paths.reports, paths.cache):
        directory.mkdir(parents=True, exist_ok=True)
    database = Database(paths.database)
    database.migrate()
    database.upsert_repository(
        fixture.git.repository_id, fixture.path, fixture.git.remote_url, "main"
    )
    task = make_task(fixture)
    task.verification.image = image
    task.verification.test_command = CommandSpec(
        argv=["python", "-c", "from calculator import add; assert add(2, 3) == 5"]
    )
    database.upsert_task(task)
    verifier = Verifier(fixture.git, paths, RepoArenaConfig(), docker=docker)

    baseline_ok, _ = verifier.validate_baseline(task)
    orchestrator = BenchmarkOrchestrator(
        fixture.git,
        paths,
        database,
        verifier,
        PatchValidator(max_files=50, max_lines=2_000),
    )
    _, completed = orchestrator.run(
        [FakeAgentRunner(task.verification.gold_source_patch)], timeout_seconds=30
    )
    rows = database.report_rows(fixture.git.repository_id)

    assert baseline_ok is True
    assert completed == 1
    assert rows[0]["status"] == RunStatus.PASS.value


@pytest.mark.docker
def test_provider_proxy_denies_non_provider_destination(tmp_path: Path) -> None:
    docker = _docker_or_skip()
    config = RepoArenaConfig().sandbox
    if not docker.image_exists(config.proxy_image) or not docker.image_exists(
        "repoarena/codex:local"
    ):
        pytest.skip("RepoArena proxy and Codex images are not built")
    script = (
        "const net=require('net');let data='';"
        "const socket=net.createConnection(3128,'proxy',()=>socket.write("
        "'CONNECT example.com:443 HTTP/1.1\\r\\nHost: example.com:443\\r\\n\\r\\n'));"
        "socket.on('data',chunk=>{data+=chunk.toString();if(data.includes('\\r\\n\\r\\n')){"
        "console.log(data.split('\\r\\n')[0]);process.exit(data.includes('403')?0:2);}});"
        "setTimeout(()=>process.exit(3),3000);"
    )

    execution = docker.run(
        image=docker.image_identity("repoarena/codex:local"),
        workspace=tmp_path,
        argv=["node", "-e", script],
        timeout_seconds=10,
        network_policy=NetworkPolicy.PROVIDER_ONLY,
        allowed_domains=[".openai.com"],
    )

    assert execution.returncode == 0, execution.stderr
    assert "403" in execution.stdout
