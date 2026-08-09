from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from test_vertical_slice import make_task

from repoarena.agents.fake import FakeAgentRunner
from repoarena.agents.router import OpenCodeRouterAgent
from repoarena.benchmark.models import (
    AgentContext,
    CommandSpec,
    RunStatus,
    SolverTaskV1,
)
from repoarena.benchmark.orchestrator import BenchmarkOrchestrator
from repoarena.benchmark.workspace import PatchValidator
from repoarena.config import RepoArenaPaths
from repoarena.config.models import NetworkPolicy, RepoArenaConfig, RouterAgentConfig
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


@pytest.mark.docker
def test_gemini_and_opencode_images_run_with_ephemeral_home(tmp_path: Path) -> None:
    docker = _docker_or_skip()
    images = (("repoarena/gemini:local", "gemini"), ("repoarena/opencode:local", "opencode"))
    if any(not docker.image_exists(image) for image, _ in images):
        pytest.skip("RepoArena Gemini and OpenCode images are not built")

    for image, executable in images:
        execution = docker.run(
            image=docker.image_identity(image),
            workspace=tmp_path,
            argv=[executable, "--version"],
            timeout_seconds=30,
            network_policy=NetworkPolicy.NONE,
            home_directory="/home/node",
        )
        assert execution.returncode == 0, execution.stderr
        assert execution.stdout.strip()

    credential = tmp_path / "gemini-credential.json"
    credential.write_text("{}", encoding="utf-8")
    mounted = docker.run(
        image=docker.image_identity("repoarena/gemini:local"),
        workspace=tmp_path,
        argv=["gemini", "--version"],
        timeout_seconds=30,
        network_policy=NetworkPolicy.NONE,
        credential_mount=(credential, "/home/node/.gemini/oauth_creds.json"),
        home_directory="/home/node",
    )
    assert mounted.returncode == 0, mounted.stderr


@pytest.mark.docker
def test_opencode_loads_custom_router_configuration_without_network(tmp_path: Path) -> None:
    docker = _docker_or_skip()
    image = "repoarena/opencode:local"
    if not docker.image_exists(image):
        pytest.skip("RepoArena OpenCode image is not built")
    config = RouterAgentConfig(
        enabled=True,
        image=image,
        executable="opencode",
        model="fixture-model",
        provider_id="router",
        base_url="http://host.docker.internal:20128/v1",
        api_key_env="ROUTER_API_KEY",
        allowed_domains=["host.docker.internal"],
    )
    agent = OpenCodeRouterAgent("router", config, docker)
    environment = agent.additional_environment()
    environment["ROUTER_API_KEY"] = "fixture-" + "router-key"

    execution = docker.run(
        image=docker.image_identity(image),
        workspace=tmp_path,
        argv=["opencode", "--pure", "models", "router"],
        timeout_seconds=30,
        network_policy=NetworkPolicy.NONE,
        environment=environment,
        home_directory="/home/node",
    )

    assert execution.returncode == 0, execution.stderr
    assert "router/fixture-model" in execution.stdout


@pytest.mark.docker
def test_provider_proxy_can_reach_allowlisted_host_router(tmp_path: Path) -> None:
    docker = _docker_or_skip()
    if not docker.image_exists(RepoArenaConfig().sandbox.proxy_image) or not docker.image_exists(
        "repoarena/opencode:local"
    ):
        pytest.skip("RepoArena proxy and OpenCode images are not built")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"router-ready")

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)  # noqa: S104 - test host endpoint
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    script = (
        "const net=require('net');let data='';"
        "const socket=net.createConnection(3128,'proxy',()=>socket.write("
        f"'GET http://host.docker.internal:{port}/ HTTP/1.1\\r\\n"
        f"Host: host.docker.internal:{port}\\r\\nConnection: close\\r\\n\\r\\n'));"
        "socket.on('data',chunk=>data+=chunk.toString());"
        "socket.on('end',()=>{console.log(data);process.exit(data.includes('router-ready')?0:2)});"
        "setTimeout(()=>process.exit(3),5000);"
    )
    try:
        execution = docker.run(
            image=docker.image_identity("repoarena/opencode:local"),
            workspace=tmp_path,
            argv=["node", "-e", script],
            timeout_seconds=10,
            network_policy=NetworkPolicy.PROVIDER_ONLY,
            allowed_domains=["host.docker.internal"],
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert execution.returncode == 0, execution.stderr
    assert "router-ready" in execution.stdout


@pytest.mark.docker
def test_router_agent_edits_workspace_through_fake_compatible_api(
    monkeypatch: object, tmp_path: Path
) -> None:
    docker = _docker_or_skip()
    if not docker.image_exists(RepoArenaConfig().sandbox.proxy_image) or not docker.image_exists(
        "repoarena/opencode:local"
    ):
        pytest.skip("RepoArena proxy and OpenCode images are not built")
    calls = 0
    tool_requested = False
    request_models: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            nonlocal calls, tool_requested
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            calls += 1
            request_models.append(payload["model"])
            tool_names = {
                tool["function"]["name"]
                for tool in payload.get("tools", [])
                if tool.get("type") == "function"
            }
            if not tool_names:
                delta = {"role": "assistant", "content": "Router fixture"}
                finish_reason = "stop"
            elif not tool_requested:
                assert "write" in tool_names
                tool_requested = True
                delta = {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_fixture_write",
                            "type": "function",
                            "function": {
                                "name": "write",
                                "arguments": json.dumps(
                                    {
                                        "filePath": "/workspace/router-proof.txt",
                                        "content": "router-agent-ok\n",
                                    },
                                    separators=(",", ":"),
                                ),
                            },
                        }
                    ],
                }
                finish_reason = "tool_calls"
            else:
                delta = {"role": "assistant", "content": "Task complete."}
                finish_reason = "stop"
            chunks = (
                {
                    "id": f"chatcmpl-fixture-{calls}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                },
                {
                    "id": f"chatcmpl-fixture-{calls}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
                },
            )
            body = (
                "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)  # noqa: S104 - test host endpoint
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    config = RouterAgentConfig(
        enabled=True,
        image="repoarena/opencode:local",
        executable="opencode",
        model="fixture-model",
        provider_id="router",
        base_url=f"http://host.docker.internal:{port}/v1",
        api_key_env="ROUTER_API_KEY",
        allowed_domains=["host.docker.internal"],
    )
    monkeypatch.setenv("ROUTER_API_KEY", "fixture-" + "router-key")
    agent = OpenCodeRouterAgent("router", config, docker)
    task = SolverTaskV1(
        id="router-fixture",
        task_description="Create router-proof.txt containing router-agent-ok.",
        languages=["Text"],
    )
    try:
        result = agent.run(
            AgentContext(workspace=str(tmp_path), timeout_seconds=60, run_id="router-run"),
            task,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.status is RunStatus.PASS, result.stderr
    assert (tmp_path / "router-proof.txt").read_text(encoding="utf-8") == "router-agent-ok\n"
    assert calls >= 2
    assert set(request_models) == {"fixture-model"}
