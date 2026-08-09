from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from repoarena.config.models import validate_image_reference


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    SETUP_ERROR = "SETUP_ERROR"
    AGENT_ERROR = "AGENT_ERROR"
    INVALID_PATCH = "INVALID_PATCH"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"


class TaskStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    VALID = "VALID"
    REJECTED = "REJECTED"


class CommandSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    argv: list[str] = Field(min_length=1)

    @field_validator("argv")
    @classmethod
    def safe_argv(cls, value: list[str]) -> list[str]:
        if any(not item or "\x00" in item for item in value):
            raise ValueError("command arguments must be non-empty and NUL-free")
        return value


class QualityReason(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signal: str
    points: int
    detail: str


class TaskMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    languages: list[str] = Field(default_factory=list)
    quality_score: int = Field(ge=0, le=100)
    quality_reasons: list[QualityReason]
    files_changed_count: int = Field(ge=0)
    lines_changed: int = Field(ge=0)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class VerifierSpecV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1"
    image: str
    setup_commands: list[CommandSpec] = Field(default_factory=list)
    test_command: CommandSpec
    hidden_test_patch: str
    gold_source_patch: str
    protected_paths: list[str]
    repetitions: int = Field(default=2, ge=1, le=5)

    @field_validator("image")
    @classmethod
    def safe_image(cls, value: str) -> str:
        return validate_image_reference(value)


class BenchmarkTaskV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1"
    id: str
    repository_id: str
    repository: str
    base_commit: str
    gold_commit: str
    task_description: str
    issue_reference: str | None = None
    pull_request_number: int
    verification: VerifierSpecV1
    metadata: TaskMetadata
    status: TaskStatus = TaskStatus.CANDIDATE

    @field_validator("base_commit", "gold_commit")
    @classmethod
    def full_git_sha(cls, value: str) -> str:
        if len(value) != 40 or any(
            character not in "0123456789abcdefABCDEF" for character in value
        ):
            raise ValueError("historical commits must be full 40-character Git SHAs")
        return value.lower()


class SolverTaskV1(BaseModel):
    """The only task data that may cross into a solver environment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1"
    id: str
    task_description: str
    languages: list[str]


class AgentContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    workspace: str
    timeout_seconds: int
    run_id: str


class AgentRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RunStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = Field(ge=0)
    model: str | None = None
    version: str | None = None
    exact_cost: float | None = Field(default=None, ge=0)


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RunStatus
    command: list[str]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = Field(ge=0)
