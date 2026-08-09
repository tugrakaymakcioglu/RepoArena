from __future__ import annotations

import hashlib
import re
from pathlib import Path

from repoarena.benchmark.models import BenchmarkTaskV1, RunStatus, VerificationResult
from repoarena.benchmark.workspace import PatchValidator, WorkspaceFactory
from repoarena.config import RepoArenaConfig, RepoArenaPaths
from repoarena.config.models import NetworkPolicy
from repoarena.exceptions import RepoArenaError, VerificationError
from repoarena.git import GitRepository
from repoarena.sandbox import DockerRunner
from repoarena.utils.process import run_process


class Verifier:
    def __init__(
        self,
        repository: GitRepository,
        paths: RepoArenaPaths,
        config: RepoArenaConfig,
        docker: DockerRunner | None = None,
    ) -> None:
        self.repository = repository
        self.paths = paths
        self.config = config
        self.docker = docker or DockerRunner(config.sandbox)
        self.patch_validator = PatchValidator(
            max_files=config.benchmark.max_patch_files,
            max_lines=config.benchmark.max_patch_lines,
            max_bytes=config.benchmark.max_patch_bytes,
        )

    def verify(self, task: BenchmarkTaskV1, agent_patch: str) -> VerificationResult:
        source = self.repository.source_with_commits([task.base_commit], self.paths.cache)
        factory = WorkspaceFactory(source)
        try:
            self.patch_validator.inspect(
                agent_patch,
                protected_paths=tuple(task.verification.protected_paths),
            )
        except RepoArenaError as exc:
            return VerificationResult(
                status=RunStatus.INVALID_PATCH,
                command=[],
                stderr=str(exc),
                duration_seconds=0,
            )
        with factory.materialize(task.base_commit, solver=False) as workspace:
            if agent_patch.strip():
                try:
                    self._apply(workspace, agent_patch)
                except RepoArenaError as exc:
                    return VerificationResult(
                        status=RunStatus.INVALID_PATCH,
                        command=[],
                        stderr=str(exc),
                        duration_seconds=0,
                    )
            try:
                self._apply(workspace, task.verification.hidden_test_patch)
            except RepoArenaError as exc:
                return VerificationResult(
                    status=RunStatus.VERIFICATION_ERROR,
                    command=[],
                    stderr=f"Hidden verifier patch failed: {exc}",
                    duration_seconds=0,
                )
            setup_stdout: list[str] = []
            setup_stderr: list[str] = []
            total_duration = 0.0
            verifier_environment = {
                "GOCACHE": "/workspace/.repoarena-gocache",
                "GOMODCACHE": "/workspace/.repoarena-gomod",
                "NPM_CONFIG_CACHE": "/workspace/.repoarena-npm-cache",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "XDG_CACHE_HOME": "/workspace/.repoarena-cache",
            }
            for command in task.verification.setup_commands:
                execution = self.docker.run(
                    image=task.verification.image,
                    workspace=workspace,
                    argv=command.argv,
                    timeout_seconds=self.config.benchmark.timeout_seconds,
                    network_policy=self.config.sandbox.setup_network,
                    environment=verifier_environment,
                )
                total_duration += execution.duration_seconds
                setup_stdout.append(execution.stdout)
                setup_stderr.append(execution.stderr)
                if execution.timed_out:
                    return VerificationResult(
                        status=RunStatus.TIMEOUT,
                        command=command.argv,
                        stdout="".join(setup_stdout),
                        stderr="".join(setup_stderr),
                        duration_seconds=total_duration,
                    )
                if execution.returncode != 0:
                    return VerificationResult(
                        status=RunStatus.SETUP_ERROR,
                        command=command.argv,
                        exit_code=execution.returncode,
                        stdout="".join(setup_stdout),
                        stderr="".join(setup_stderr),
                        duration_seconds=total_duration,
                    )
            command = task.verification.test_command
            execution = self.docker.run(
                image=task.verification.image,
                workspace=workspace,
                argv=command.argv,
                timeout_seconds=self.config.benchmark.timeout_seconds,
                network_policy=NetworkPolicy.NONE,
                environment=verifier_environment,
            )
            total_duration += execution.duration_seconds
            if execution.timed_out:
                status = RunStatus.TIMEOUT
            elif execution.returncode == 0:
                status = RunStatus.PASS
            else:
                status = RunStatus.FAIL
            return VerificationResult(
                status=status,
                command=command.argv,
                exit_code=execution.returncode,
                stdout="".join(setup_stdout) + execution.stdout,
                stderr="".join(setup_stderr) + execution.stderr,
                duration_seconds=total_duration,
            )

    def validate_baseline(self, task: BenchmarkTaskV1) -> tuple[bool, str]:
        if not self.docker.image_exists(task.verification.image):
            task.verification.image = self.docker.pull_image(task.verification.image)
        else:
            task.verification.image = self.docker.image_identity(task.verification.image)
        base_results = [self.verify(task, "") for _ in range(task.verification.repetitions)]
        if any(result.status is not RunStatus.FAIL for result in base_results):
            statuses = ", ".join(result.status.value for result in base_results)
            return False, f"base must fail reproducibly; got {statuses}"
        signatures = {_failure_signature(result) for result in base_results}
        if len(signatures) != 1:
            return False, "base failure diagnostics were not reproducible"
        gold_results = [
            self.verify(task, task.verification.gold_source_patch)
            for _ in range(task.verification.repetitions)
        ]
        if any(result.status is not RunStatus.PASS for result in gold_results):
            statuses = ", ".join(result.status.value for result in gold_results)
            return False, f"gold must pass reproducibly; got {statuses}"
        return True, "base fails and gold passes reproducibly"

    @staticmethod
    def _apply(workspace: Path, patch: str) -> None:
        checked = run_process(
            ["git", "apply", "--check", "--whitespace=nowarn", "-"],
            cwd=workspace,
            input_text=patch,
            check=False,
        )
        if checked.returncode != 0:
            raise VerificationError(checked.stderr.strip() or "Patch does not apply")
        applied = run_process(
            ["git", "apply", "--index", "--whitespace=nowarn", "-"],
            cwd=workspace,
            input_text=patch,
            check=False,
        )
        if applied.returncode != 0:
            raise VerificationError(applied.stderr.strip() or "Patch application failed")


def _failure_signature(result: VerificationResult) -> str:
    diagnostic = result.stdout + "\n" + result.stderr
    diagnostic = re.sub(r"repoarena-verifier-[^\\/\s]+", "workspace", diagnostic)
    diagnostic = re.sub(r"\b\d+(?:\.\d+)?s\b", "TIME", diagnostic)
    important = [
        line.strip()
        for line in diagnostic.splitlines()
        if any(marker in line for marker in ("FAILED", "ERROR", "AssertionError", "assert "))
    ]
    normalized = "\n".join(important) or diagnostic[-4_000:]
    return hashlib.sha256(normalized.encode("utf-8", "replace")).hexdigest()
