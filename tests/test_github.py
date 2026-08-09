from __future__ import annotations

from repoarena.config.models import GitHubConfig
from repoarena.discovery.github import GitHubMetadataSource


def test_github_metadata_hydrates_linked_issue_and_check_run_evidence() -> None:
    source = GitHubMetadataSource("https://github.com/example/project.git", GitHubConfig())
    endpoints: list[str] = []

    def get(endpoint: str) -> dict[str, object]:
        endpoints.append(endpoint)
        if endpoint.endswith("issues/4"):
            return {
                "number": 4,
                "title": "Fix arithmetic",
                "body": "The arithmetic result is incorrect and needs a focused correction.",
                "html_url": "https://github.com/example/project/issues/4",
            }
        if endpoint.endswith("/status"):
            return {"state": "pending"}
        if endpoint.endswith("/check-runs"):
            return {
                "check_runs": [
                    {"status": "completed", "conclusion": "success"},
                    {"status": "completed", "conclusion": "skipped"},
                ]
            }
        raise AssertionError(endpoint)

    pulls = source._hydrate(
        [
            {
                "number": 8,
                "title": "Fix arithmetic",
                "body": "Fixes #4",
                "html_url": "https://github.com/example/project/pull/8",
                "merge_commit_sha": "a" * 40,
                "merged_at": "2026-01-01T00:00:00Z",
            }
        ],
        get,
        None,
    )

    assert len(pulls) == 1
    assert pulls[0].issue is not None
    assert pulls[0].issue.number == 4
    assert pulls[0].ci_success is True
    assert any(endpoint.endswith("check-runs") for endpoint in endpoints)
