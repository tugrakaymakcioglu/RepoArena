"""Domain-specific exceptions presented by the CLI."""


class RepoArenaError(Exception):
    """Base exception for expected RepoArena failures."""


class ConfigurationError(RepoArenaError):
    """Configuration is absent, invalid, or unsafe."""


class RepositoryError(RepoArenaError):
    """The target Git repository cannot satisfy an operation."""


class DiscoveryError(RepoArenaError):
    """Historical metadata could not be discovered safely."""


class SandboxError(RepoArenaError):
    """An isolated execution environment failed."""


class AgentError(RepoArenaError):
    """A coding-agent adapter failed."""


class VerificationError(RepoArenaError):
    """Independent verification could not be completed."""


class StorageError(RepoArenaError):
    """Local state could not be read or persisted."""
