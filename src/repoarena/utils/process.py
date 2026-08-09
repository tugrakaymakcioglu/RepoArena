from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from repoarena.exceptions import RepoArenaError


@dataclass(frozen=True, slots=True)
class ProcessResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class ProcessFailure(RepoArenaError):
    def __init__(self, result: ProcessResult) -> None:
        self.result = result
        command = " ".join(result.argv)
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        super().__init__(f"Command failed ({result.returncode}): {command}\n{detail}")


def run_process(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    timeout: float | None = None,
    check: bool = True,
) -> ProcessResult:
    if not argv or any("\x00" in item for item in argv):
        raise ValueError("argv must contain non-empty, NUL-free arguments")
    child_env = None
    if env is not None:
        child_env = os.environ.copy()
        child_env.update(env)
    completed = subprocess.run(
        list(argv),
        cwd=cwd,
        env=child_env,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        shell=False,
    )
    result = ProcessResult(tuple(argv), completed.returncode, completed.stdout, completed.stderr)
    if check and result.returncode != 0:
        raise ProcessFailure(result)
    return result


def run_process_bytes(
    argv: Sequence[str], *, cwd: Path | None = None, timeout: float | None = None
) -> bytes:
    completed = subprocess.run(
        list(argv),
        cwd=cwd,
        capture_output=True,
        timeout=timeout,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        result = ProcessResult(
            tuple(argv),
            completed.returncode,
            completed.stdout.decode("utf-8", "replace"),
            completed.stderr.decode("utf-8", "replace"),
        )
        raise ProcessFailure(result)
    return completed.stdout
