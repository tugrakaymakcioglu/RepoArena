from __future__ import annotations

from abc import ABC, abstractmethod

from repoarena.benchmark.models import AgentContext, AgentRunResult, SolverTaskV1


class AgentRunner(ABC):
    name: str

    @abstractmethod
    def validate_environment(self) -> list[str]:
        """Return actionable environment errors; an empty list means ready."""
        raise NotImplementedError

    def prepare(self, context: AgentContext) -> None:
        """Hook for provider-specific preparation."""
        return None

    @abstractmethod
    def run(self, context: AgentContext, task: SolverTaskV1) -> AgentRunResult:
        raise NotImplementedError

    def cleanup(self) -> None:
        """Hook for provider-specific cleanup."""
        return None
