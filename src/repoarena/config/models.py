from __future__ import annotations

from enum import StrEnum
from re import Pattern
from re import compile as compile_pattern

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NetworkPolicy(StrEnum):
    NONE = "none"
    BRIDGE = "bridge"
    PROVIDER_ONLY = "provider-only"


class BenchmarkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality_threshold: int = Field(default=70, ge=0, le=100)
    timeout_seconds: int = Field(default=900, ge=1, le=86_400)
    baseline_repetitions: int = Field(default=2, ge=1, le=5)
    max_patch_files: int = Field(default=50, ge=1, le=10_000)
    max_patch_lines: int = Field(default=2_000, ge=1, le=1_000_000)
    max_patch_bytes: int = Field(default=5_000_000, ge=1_024, le=100_000_000)


class SandboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: str = "docker"
    cpus: float = Field(default=2.0, gt=0, le=64)
    memory: str = "4g"
    pids_limit: int = Field(default=512, ge=16, le=32_768)
    solver_network: NetworkPolicy = NetworkPolicy.PROVIDER_ONLY
    setup_network: NetworkPolicy = NetworkPolicy.BRIDGE
    proxy_image: str = "repoarena/egress-proxy:local"

    @field_validator("engine")
    @classmethod
    def docker_only(cls, value: str) -> str:
        if value != "docker":
            raise ValueError("V1 supports only the docker sandbox engine")
        return value

    @field_validator("memory")
    @classmethod
    def valid_memory_limit(cls, value: str) -> str:
        if not compile_pattern(r"[1-9][0-9]*(?:[bkmgBKMG])?").fullmatch(value):
            raise ValueError("memory must be a positive Docker size such as 512m or 4g")
        return value.lower()

    @field_validator("proxy_image")
    @classmethod
    def safe_proxy_image(cls, value: str) -> str:
        return validate_image_reference(value)


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    image: str
    executable: str
    model: str | None = None
    credential_file: str | None = None
    allowed_domains: list[str] = Field(default_factory=list)

    @field_validator("image")
    @classmethod
    def safe_image(cls, value: str) -> str:
        return validate_image_reference(value)

    @field_validator("executable")
    @classmethod
    def non_empty_executable(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("value must be non-empty and NUL-free")
        return value

    @field_validator("allowed_domains")
    @classmethod
    def validate_domains(cls, values: list[str]) -> list[str]:
        domain = re_compile_domain()
        if any(len(value) > 253 or not domain.fullmatch(value) for value in values):
            raise ValueError("allowed_domains must contain DNS suffixes only")
        return values


def re_compile_domain() -> Pattern[str]:
    label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    return compile_pattern(rf"\.?{label}(?:\.{label})*")


def validate_image_reference(value: str) -> str:
    if (
        not value
        or value.startswith("-")
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise ValueError("Docker image reference is unsafe")
    return value


class AgentsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codex: AgentConfig = Field(
        default_factory=lambda: AgentConfig(
            image="repoarena/codex:local",
            executable="codex",
            allowed_domains=[
                ".openai.com",
                ".chatgpt.com",
                ".oaistatic.com",
                ".oaiusercontent.com",
            ],
        )
    )
    claude: AgentConfig = Field(
        default_factory=lambda: AgentConfig(
            image="repoarena/claude:local",
            executable="claude",
            allowed_domains=[".anthropic.com", ".claude.ai"],
        )
    )


class GitHubConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = "auto"
    request_timeout_seconds: int = Field(default=30, ge=1, le=300)

    @field_validator("source")
    @classmethod
    def supported_source(cls, value: str) -> str:
        if value not in {"auto", "gh", "http"}:
            raise ValueError("source must be auto, gh, or http")
        return value


class VerificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str = "auto"
    image: str | None = None
    setup_commands: list[list[str]] = Field(default_factory=list)
    test_command: list[str] = Field(default_factory=list)

    @field_validator("image")
    @classmethod
    def safe_custom_image(cls, value: str | None) -> str | None:
        return validate_image_reference(value) if value is not None else None

    @model_validator(mode="after")
    def custom_profile_is_complete(self) -> VerificationConfig:
        if self.profile == "custom" and (not self.image or not self.test_command):
            raise ValueError("custom verification requires image and test_command")
        return self


class RepoArenaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    benchmark: BenchmarkConfig = Field(default_factory=BenchmarkConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
