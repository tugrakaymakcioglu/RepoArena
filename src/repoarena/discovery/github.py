from __future__ import annotations

import json
import os
import re
import shutil
from abc import ABC, abstractmethod
from collections.abc import Callable

import httpx

from repoarena.config.models import GitHubConfig
from repoarena.discovery.models import IssueMetadata, PullRequestMetadata
from repoarena.exceptions import DiscoveryError
from repoarena.git import github_slug
from repoarena.utils.process import run_process

_ISSUE_REFERENCE = re.compile(
    r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:[\w.-]+/[\w.-]+)?#(\d+)"
)


class MetadataSource(ABC):
    @abstractmethod
    def merged_pull_requests(self, *, limit: int | None = None) -> list[PullRequestMetadata]:
        raise NotImplementedError


class GitHubMetadataSource(MetadataSource):
    def __init__(self, remote_url: str, config: GitHubConfig) -> None:
        self.owner, self.repository = github_slug(remote_url)
        self.config = config
        self.token = os.environ.get("GITHUB_TOKEN")

    def merged_pull_requests(self, *, limit: int | None = None) -> list[PullRequestMetadata]:
        if self.config.source in {"auto", "gh"} and self._gh_ready():
            return self._through_gh(limit)
        if self.config.source == "gh":
            raise DiscoveryError("GitHub CLI is unavailable or not authenticated")
        return self._through_http(limit)

    def _gh_ready(self) -> bool:
        if not shutil.which("gh"):
            return False
        return run_process(["gh", "auth", "status"], check=False).returncode == 0

    def _through_gh(self, limit: int | None) -> list[PullRequestMetadata]:
        endpoint = f"repos/{self.owner}/{self.repository}/pulls?state=closed&per_page=100"
        result = run_process(["gh", "api", "--paginate", "--slurp", endpoint])
        pages = json.loads(result.stdout)
        raw_pulls = [item for page in pages for item in page]
        return self._hydrate(raw_pulls, self._gh_get, limit)

    def _gh_get(self, endpoint: str) -> dict[str, object]:
        result = run_process(["gh", "api", endpoint])
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise DiscoveryError(f"Unexpected GitHub response for {endpoint}")
        return value

    def _through_http(self, limit: int | None) -> list[PullRequestMetadata]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        base = f"https://api.github.com/repos/{self.owner}/{self.repository}"
        raw_pulls: list[dict[str, object]] = []
        with httpx.Client(headers=headers, timeout=self.config.request_timeout_seconds) as client:
            page = 1
            merged_count = 0
            while limit is None or merged_count < limit:
                response = client.get(
                    f"{base}/pulls", params={"state": "closed", "per_page": 100, "page": page}
                )
                self._raise_http(response)
                batch = response.json()
                if not isinstance(batch, list) or not batch:
                    break
                raw_pulls.extend(batch)
                merged_count += sum(
                    bool(pull.get("merged_at") and pull.get("merge_commit_sha"))
                    for pull in batch
                    if isinstance(pull, dict)
                )
                page += 1
                if len(batch) < 100:
                    break

            def get(endpoint: str) -> dict[str, object]:
                response = client.get(f"https://api.github.com/{endpoint}")
                self._raise_http(response)
                value = response.json()
                if not isinstance(value, dict):
                    raise DiscoveryError(f"Unexpected GitHub response for {endpoint}")
                return value

            return self._hydrate(raw_pulls, get, limit)

    @staticmethod
    def _raise_http(response: httpx.Response) -> None:
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            raise DiscoveryError(
                "GitHub API rate limit exhausted; authenticate gh or set GITHUB_TOKEN"
            )
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DiscoveryError(f"GitHub request failed: {exc}") from exc

    def _hydrate(
        self,
        raw_pulls: list[dict[str, object]],
        get: Callable[[str], dict[str, object]],
        limit: int | None,
    ) -> list[PullRequestMetadata]:
        merged = [
            pull for pull in raw_pulls if pull.get("merged_at") and pull.get("merge_commit_sha")
        ]
        if limit is not None:
            merged = merged[:limit]
        output: list[PullRequestMetadata] = []
        for pull in merged:
            body = str(pull.get("body") or "")
            references = _ISSUE_REFERENCE.findall(body)
            issue = None
            if references:
                issue_data = get(f"repos/{self.owner}/{self.repository}/issues/{references[0]}")
                if "pull_request" not in issue_data:
                    issue = IssueMetadata(
                        number=int(str(issue_data["number"])),
                        title=str(issue_data.get("title") or ""),
                        body=str(issue_data.get("body") or ""),
                        url=str(issue_data.get("html_url") or ""),
                    )
            sha = str(pull["merge_commit_sha"])
            output.append(
                PullRequestMetadata(
                    number=int(str(pull["number"])),
                    title=str(pull.get("title") or ""),
                    body=body,
                    url=str(pull.get("html_url") or ""),
                    merge_commit=sha,
                    merged_at=str(pull["merged_at"]),
                    issue=issue,
                    ci_success=self._ci_succeeded(get, sha),
                )
            )
        return output

    def _ci_succeeded(self, get: Callable[[str], dict[str, object]], commit: str) -> bool:
        status = get(f"repos/{self.owner}/{self.repository}/commits/{commit}/status")
        if status.get("state") == "success":
            return True
        checks = get(f"repos/{self.owner}/{self.repository}/commits/{commit}/check-runs")
        raw_runs = checks.get("check_runs")
        if not isinstance(raw_runs, list) or not raw_runs:
            return False
        accepted = {"success", "neutral", "skipped"}
        return all(
            isinstance(run, dict)
            and run.get("status") == "completed"
            and run.get("conclusion") in accepted
            for run in raw_runs
        )
