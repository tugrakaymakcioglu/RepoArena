from __future__ import annotations

import json
import os
from pathlib import Path

from repoarena.agents.base import AgentRunner
from repoarena.benchmark.models import AgentContext, AgentRunResult, RunStatus, SolverTaskV1
from repoarena.config.models import AgentConfig, NetworkPolicy
from repoarena.sandbox import DockerRunner


class DockerCliAgent(AgentRunner):
    credential_environment: str
    credential_target: str

    def __init__(self, config: AgentConfig, docker: DockerRunner) -> None:
        self.config = config
        self.docker = docker
        self._resolved_image: str | None = None
        self._detected_version: str | None = None

    def validate_environment(self) -> list[str]:
        errors: list[str] = []
        if not self.docker.daemon_ready():
            errors.append("Docker daemon is not reachable")
        elif not self.docker.image_exists(self.config.image):
            errors.append(f"Docker image is missing: {self.config.image}")
        else:
            self._resolved_image = self.docker.image_identity(self.config.image)
            self._detected_version = self.docker.executable_version(
                self._resolved_image, self.config.executable
            )
            if self._detected_version is None:
                errors.append(
                    f"{self.config.executable} is unavailable in image {self.config.image}"
                )
        if not os.environ.get(self.credential_environment) and not self._credential_mount():
            errors.append(
                f"No {self.credential_environment} or readable credential_file is configured"
            )
        return errors

    def run(self, context: AgentContext, task: SolverTaskV1) -> AgentRunResult:
        environment: dict[str, str] = {}
        if value := os.environ.get(self.credential_environment):
            environment[self.credential_environment] = value
        execution = self.docker.run(
            image=self._resolved_image or self.config.image,
            workspace=Path(context.workspace),
            argv=self.command(),
            timeout_seconds=context.timeout_seconds,
            network_policy=NetworkPolicy.PROVIDER_ONLY,
            allowed_domains=self.config.allowed_domains,
            environment=environment,
            input_text=self.prompt(task),
            credential_mount=self._credential_mount(),
            home_directory="/home/node",
        )
        if execution.timed_out:
            status = RunStatus.TIMEOUT
        elif execution.returncode == 0:
            status = RunStatus.PASS
        else:
            status = RunStatus.AGENT_ERROR
        return AgentRunResult(
            status=status,
            exit_code=execution.returncode,
            stdout=execution.stdout,
            stderr=execution.stderr,
            duration_seconds=execution.duration_seconds,
            model=self.config.model or self.extract_model(execution.stdout),
            version=self._detected_version or self._resolved_image,
            exact_cost=self.extract_exact_cost(execution.stdout),
        )

    def _credential_mount(self) -> tuple[Path, str] | None:
        if not self.config.credential_file:
            return None
        path = Path(self.config.credential_file).expanduser()
        return (path, self.credential_target) if path.is_file() else None

    @staticmethod
    def prompt(task: SolverTaskV1) -> str:
        languages = ", ".join(task.languages) or "unknown"
        return (
            "Solve the repository task below. Work only inside the current workspace. "
            "Do not search for the original issue, pull request, repository, or human solution. "
            "Do not commit. Make the smallest correct source change and leave it in the working tree.\n\n"
            f"Task ID: {task.id}\nLanguages: {languages}\n\n{task.task_description}\n"
        )

    @staticmethod
    def extract_exact_cost(output: str) -> float | None:
        for line in reversed(output.splitlines()):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            value = event.get("total_cost_usd") if isinstance(event, dict) else None
            if isinstance(value, int | float) and value >= 0:
                return float(value)
        return None

    @staticmethod
    def extract_model(output: str) -> str | None:
        for line in reversed(output.splitlines()):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            for key in ("model", "model_name"):
                value = event.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    def command(self) -> list[str]:
        raise NotImplementedError
