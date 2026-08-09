from __future__ import annotations

from pathlib import Path

from repoarena.config.models import SandboxConfig
from repoarena.sandbox.docker import DockerRunner
from repoarena.utils.process import ProcessResult


def test_docker_command_enforces_isolation(monkeypatch: object, tmp_path: Path) -> None:
    captured: list[tuple[str, ...]] = []

    def fake_run_process(argv: list[str], **kwargs: object) -> ProcessResult:
        del kwargs
        captured.append(tuple(argv))
        return ProcessResult(tuple(argv), 0, "ok", "")

    monkeypatch.setattr("repoarena.sandbox.docker.run_process", fake_run_process)
    runner = DockerRunner(SandboxConfig())
    execution = runner._run_container(
        image="sha256:fixture",
        workspace=tmp_path,
        argv=["python", "-V"],
        timeout_seconds=10,
        network="none",
        environment={},
        input_text=None,
        credential_mount=None,
        home_directory="/tmp",
    )

    command = captured[0]
    assert execution.returncode == 0
    assert "--read-only" in command
    assert command[command.index("--cap-drop") : command.index("--cap-drop") + 2] == (
        "--cap-drop",
        "ALL",
    )
    assert "no-new-privileges" in command
    assert command[command.index("--network") + 1] == "none"
    assert "--pids-limit" in command
    assert "--cpus" in command
    assert "--memory" in command
    assert not any("docker.sock" in item for item in command)
