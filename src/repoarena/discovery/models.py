from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class IssueMetadata:
    number: int
    title: str
    body: str
    url: str


@dataclass(frozen=True, slots=True)
class PullRequestMetadata:
    number: int
    title: str
    body: str
    url: str
    merge_commit: str
    merged_at: str
    issue: IssueMetadata | None = None
    ci_success: bool = False


@dataclass(slots=True)
class DiscoveryStats:
    merged_prs: int = 0
    linked_issues: int = 0
    potential_candidates: int = 0
    valid_tasks: int = 0
    rejected: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1
