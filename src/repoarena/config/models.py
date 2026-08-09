from __future__ import annotations

from enum import StrEnum
from re import Pattern
from re import compile as compile_pattern
from urllib.parse import urlsplit

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

    @field_validator("model")
    @classmethod
    def safe_model(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.strip()
            or value != value.strip()
            or any(character.isspace() or ord(character) < 32 for character in value)
        ):
            raise ValueError("model must be a non-empty, whitespace-free identifier")
        return value

    @field_validator("allowed_domains")
    @classmethod
    def validate_domains(cls, values: list[str]) -> list[str]:
        domain = re_compile_domain()
        if any(len(value) > 253 or not domain.fullmatch(value) for value in values):
            raise ValueError("allowed_domains must contain DNS suffixes only")
        return [value.lower() for value in values]


class EnvironmentAgentConfig(AgentConfig):
    """Agent authentication that is intentionally limited to an environment variable."""

    @model_validator(mode="after")
    def no_credential_file(self) -> EnvironmentAgentConfig:
        if self.credential_file is not None:
            raise ValueError("this agent supports environment-backed API keys, not credential_file")
        return self


class RouterAgentConfig(AgentConfig):
    """Configuration for an OpenAI-compatible endpoint used through OpenCode."""

    provider_id: str = "router"
    base_url: str
    api_key_env: str

    @field_validator("provider_id")
    @classmethod
    def safe_provider_id(cls, value: str) -> str:
        if not compile_pattern(r"[a-z][a-z0-9_-]{0,63}").fullmatch(value):
            raise ValueError("provider_id must be a lowercase provider identifier")
        return value

    @field_validator("api_key_env")
    @classmethod
    def safe_api_key_environment(cls, value: str) -> str:
        if not compile_pattern(r"[A-Za-z_][A-Za-z0-9_]*").fullmatch(value):
            raise ValueError("api_key_env must be an environment variable name")
        return value

    @field_validator("base_url")
    @classmethod
    def safe_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("base_url contains an invalid port") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "base_url must be an HTTP(S) URL without credentials, query, or fragment"
            )
        if parsed.scheme == "http" and parsed.hostname != "host.docker.internal":
            raise ValueError("plain HTTP router URLs must use host.docker.internal")
        if parsed.scheme == "https" and port not in {None, 443}:
            raise ValueError("HTTPS router URLs must use port 443 with provider-only networking")
        return value.rstrip("/")

    @model_validator(mode="after")
    def enabled_router_is_complete(self) -> RouterAgentConfig:
        if self.credential_file is not None:
            raise ValueError(
                "router agents support environment-backed API keys, not credential_file"
            )
        if self.enabled and self.model is None:
            raise ValueError("enabled router agents require a model")
        host = urlsplit(self.base_url).hostname
        covered = host is not None and any(
            host == suffix.lstrip(".") or (suffix.startswith(".") and host.endswith(suffix))
            for suffix in self.allowed_domains
        )
        if not covered:
            raise ValueError("base_url host must be covered by allowed_domains")
        return self


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
    gemini: EnvironmentAgentConfig = Field(
        default_factory=lambda: EnvironmentAgentConfig(
            enabled=False,
            image="repoarena/gemini:local",
            executable="gemini",
            allowed_domains=[".googleapis.com"],
        )
    )
    openrouter: RouterAgentConfig = Field(
        default_factory=lambda: RouterAgentConfig(
            enabled=False,
            image="repoarena/opencode:local",
            executable="opencode",
            provider_id="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
            allowed_domains=[".openrouter.ai"],
        )
    )
    router: RouterAgentConfig = Field(
        default_factory=lambda: RouterAgentConfig(
            enabled=False,
            image="repoarena/opencode:local",
            executable="opencode",
            provider_id="router",
            base_url="http://host.docker.internal:20128/v1",
            api_key_env="ROUTER_API_KEY",
            allowed_domains=["host.docker.internal"],
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
