from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from rich.console import Console
from rich.table import Table

from repoarena.config import RepoArenaPaths, load_config
from repoarena.exceptions import RepoArenaError
from repoarena.git import GitRepository
from repoarena.sandbox import DockerRunner
from repoarena.storage import Database
from repoarena.utils.process import run_process


class CheckLevel(StrEnum):
    OK = "OK"
    WARN = "WARN"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    level: CheckLevel
    detail: str


def collect_checks(paths: RepoArenaPaths) -> list[DoctorCheck]:
    config = load_config(paths)
    checks: list[DoctorCheck] = []
    git = shutil.which("git")
    checks.append(
        DoctorCheck(
            "Git",
            CheckLevel.OK if git else CheckLevel.ERROR,
            git or "Install Git and add it to PATH",
        )
    )
    GitRepository(paths.repository)
    checks.append(DoctorCheck("Repository", CheckLevel.OK, str(paths.repository)))
    dirty = run_process(["git", "status", "--porcelain"], cwd=paths.repository, check=False).stdout
    checks.append(
        DoctorCheck(
            "Working tree",
            CheckLevel.WARN if dirty else CheckLevel.OK,
            "Uncommitted changes are safe; benchmarks never modify this checkout"
            if dirty
            else "Clean",
        )
    )
    docker_exe = shutil.which("docker")
    if not docker_exe:
        checks.append(DoctorCheck("Docker CLI", CheckLevel.ERROR, "Install Docker"))
    else:
        checks.append(DoctorCheck("Docker CLI", CheckLevel.OK, docker_exe))
        docker = DockerRunner(config.sandbox)
        daemon_ready = docker.daemon_ready()
        checks.append(
            DoctorCheck(
                "Docker daemon",
                CheckLevel.OK if daemon_ready else CheckLevel.ERROR,
                "Reachable" if daemon_ready else "Start Docker Desktop or dockerd",
            )
        )
        for label, image, build in (
            ("Egress proxy", config.sandbox.proxy_image, "docker/sandbox/proxy.Dockerfile"),
            ("Codex image", config.agents.codex.image, "docker/agents/codex.Dockerfile"),
            ("Claude image", config.agents.claude.image, "docker/agents/claude.Dockerfile"),
        ):
            exists = daemon_ready and docker.image_exists(image)
            checks.append(
                DoctorCheck(
                    label,
                    CheckLevel.OK if exists else CheckLevel.ERROR,
                    image if exists else f"Build {build} as {image}",
                )
            )
        for label, agent in (
            ("Codex CLI", config.agents.codex),
            ("Claude CLI", config.agents.claude),
        ):
            if daemon_ready and docker.image_exists(agent.image):
                identity = docker.image_identity(agent.image)
                version = docker.executable_version(identity, agent.executable)
                checks.append(
                    DoctorCheck(
                        label,
                        CheckLevel.OK if version else CheckLevel.ERROR,
                        version or f"{agent.executable} --version failed in {agent.image}",
                    )
                )
    gh = shutil.which("gh")
    if gh and run_process(["gh", "auth", "status"], check=False).returncode == 0:
        checks.append(DoctorCheck("GitHub metadata", CheckLevel.OK, "Authenticated GitHub CLI"))
    elif os.environ.get("GITHUB_TOKEN"):
        checks.append(DoctorCheck("GitHub metadata", CheckLevel.OK, "GITHUB_TOKEN configured"))
    else:
        checks.append(
            DoctorCheck(
                "GitHub metadata",
                CheckLevel.WARN,
                "Using unauthenticated public API with a low rate limit",
            )
        )
    _credential_check(checks, "Codex auth", "OPENAI_API_KEY", config.agents.codex.credential_file)
    _credential_check(
        checks, "Claude auth", "ANTHROPIC_API_KEY", config.agents.claude.credential_file
    )
    return checks


def _credential_check(
    checks: list[DoctorCheck], label: str, variable: str, configured_file: str | None
) -> None:
    file_ready = bool(configured_file and Path(configured_file).expanduser().is_file())
    ready = bool(os.environ.get(variable)) or file_ready
    detail = (
        f"{variable} or configured credential file is available"
        if ready
        else (f"Set {variable} or agents.*.credential_file; secrets are never persisted")
    )
    checks.append(DoctorCheck(label, CheckLevel.OK if ready else CheckLevel.ERROR, detail))


def run_doctor(
    console: Console,
    context: Callable[[], tuple[RepoArenaPaths, Database]],
) -> int:
    try:
        paths, _ = context()
        checks = collect_checks(paths)
    except RepoArenaError as exc:
        console.print(f"[red]Doctor failed:[/red] {exc}")
        return 1
    table = Table(title="RepoArena environment")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    colors = {CheckLevel.OK: "green", CheckLevel.WARN: "yellow", CheckLevel.ERROR: "red"}
    for check in checks:
        table.add_row(check.name, f"[{colors[check.level]}]{check.level.value}[/]", check.detail)
    console.print(table)
    errors = sum(check.level is CheckLevel.ERROR for check in checks)
    warnings = sum(check.level is CheckLevel.WARN for check in checks)
    console.print(f"{errors} errors, {warnings} warnings")
    return 1 if errors else 0
