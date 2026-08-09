from __future__ import annotations

import re
from pathlib import Path


def test_readme_local_links_and_core_positioning() -> None:
    repository = Path(__file__).resolve().parents[1]
    readme = (repository / "README.md").read_text(encoding="utf-8")

    assert "SWE-bench for your own repository" in readme
    assert "Your repository and benchmark results stay on your machine" in readme
    assert "uv tool install ." in readme
    for target in re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", readme):
        if target.startswith(("http://", "https://", "#")):
            continue
        path = target.split("#", 1)[0]
        assert (repository / path).exists(), f"README link does not exist: {target}"


def test_recommended_topics_are_focused_and_github_compatible() -> None:
    repository = Path(__file__).resolve().parents[1]
    metadata = (repository / "docs" / "repository-metadata.md").read_text(encoding="utf-8")
    topic_block = re.search(r"## Topics\s+```text\s+(.+?)```", metadata, re.DOTALL)

    assert topic_block is not None
    topics = topic_block.group(1).split()
    assert len(topics) <= 20
    assert len(topics) == len(set(topics))
    assert all(re.fullmatch(r"[a-z0-9-]{1,50}", topic) for topic in topics)
