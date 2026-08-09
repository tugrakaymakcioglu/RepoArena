from __future__ import annotations

import time
from pathlib import Path

from repoarena.agents.base import AgentRunner
from repoarena.benchmark.models import AgentContext, AgentRunResult, RunStatus, SolverTaskV1
from repoarena.utils.process import run_process


class FakeAgentRunner(AgentRunner):
    name = "fake"

    def __init__(self, patch: str, *, exit_code: int = 0) -> None:
        self.patch = patch
        self.exit_code = exit_code

    def validate_environment(self) -> list[str]:
        return []

    def run(self, context: AgentContext, task: SolverTaskV1) -> AgentRunResult:
        del task
        started = time.monotonic()
        if self.exit_code != 0:
            return AgentRunResult(
                status=RunStatus.AGENT_ERROR,
                exit_code=self.exit_code,
                stderr="Fake agent failed as configured.",
                duration_seconds=time.monotonic() - started,
                version="test",
            )
        if self.patch:
            result = run_process(
                ["git", "apply", "--whitespace=nowarn", "-"],
                cwd=Path(context.workspace),
                input_text=self.patch,
                check=False,
            )
            if result.returncode != 0:
                return AgentRunResult(
                    status=RunStatus.AGENT_ERROR,
                    exit_code=result.returncode,
                    stderr=result.stderr,
                    duration_seconds=time.monotonic() - started,
                    version="test",
                )
        return AgentRunResult(
            status=RunStatus.PASS,
            exit_code=0,
            stdout="Fake agent completed.",
            duration_seconds=time.monotonic() - started,
            version="test",
        )
