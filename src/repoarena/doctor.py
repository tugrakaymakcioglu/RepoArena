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
    agent_specs = tuple(
        spec
        for spec in (
            (
                "Codex",
                config.agents.codex,
                "OPENAI_API_KEY",
                "docker/agents/codex.Dockerfile",
            ),
            (
                "Claude",
                config.agents.claude,
                "ANTHROPIC_API_KEY",
                "docker/agents/claude.Dockerfile",
            ),
            (
                "Gemini",
                config.agents.gemini,
                "GEMINI_API_KEY",
                "docker/agents/gemini.Dockerfile",
            ),
            (
                "OpenRouter",
                config.agents.openrouter,
                config.agents.openrouter.api_key_env,
                "docker/agents/opencode.Dockerfile",
            ),
            (
                "Router",
                config.agents.router,
                config.agents.router.api_key_env,
                "docker/agents/opencode.Dockerfile",
            ),
        )
        if spec[1].enabled
    )
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
        image_specs: dict[str, tuple[str, str]] = {
            config.sandbox.proxy_image: (
                "Egress proxy",
                "docker/sandbox/proxy.Dockerfile",
            )
        }
        for label, agent, _, build in agent_specs:
            existing = image_specs.get(agent.image)
            image_specs[agent.image] = (
                f"{existing[0]} / {label} image" if existing else f"{label} image",
                build,
            )
        for image, (label, build) in image_specs.items():
            exists = daemon_ready and docker.image_exists(image)
            checks.append(
                DoctorCheck(
                    label,
                    CheckLevel.OK if exists else CheckLevel.ERROR,
                    image if exists else f"Build {build} as {image}",
                )
            )
        for label, agent, _, _ in agent_specs:
            if daemon_ready and docker.image_exists(agent.image):
                identity = docker.image_identity(agent.image)
                version = docker.executable_version(identity, agent.executable)
                checks.append(
                    DoctorCheck(
                        f"{label} CLI",
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
    for label, agent, variable, _ in agent_specs:
        _credential_check(checks, f"{label} auth", variable, agent.credential_file)
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
