from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


def test_readme_local_links_and_core_positioning() -> None:
    repository = Path(__file__).resolve().parents[1]
    readme = (repository / "README.md").read_text(encoding="utf-8")

    assert "SWE-bench for your own repository" in readme
    assert "Your repository and benchmark results stay on your machine" in readme
    assert "uv tool install ." in readme
    assert "GEMINI_API_KEY" in (repository / "docs" / "providers.md").read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY" in (repository / "docs" / "providers.md").read_text(
        encoding="utf-8"
    )
    assert "host.docker.internal:20128/v1" in (repository / "docs" / "providers.md").read_text(
        encoding="utf-8"
    )
    for target in re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", readme):
        if target.startswith(("http://", "https://", "#")):
            continue
        path = target.split("#", 1)[0]
        assert (repository / path).exists(), f"README link does not exist: {target}"


def test_readme_visual_assets_are_local_and_bounded() -> None:
    repository = Path(__file__).resolve().parents[1]
    readme = (repository / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"!\[[^]]*\]\(([^)]+)\)", readme)

    expected = {
        "docs/assets/repoarena-hero.webp",
        "docs/assets/benchmark-pipeline.svg",
        "docs/assets/cli-demo.gif",
        "docs/assets/isolation-flow.gif",
    }
    assert expected <= set(targets)
    for target in expected:
        asset = repository / target
        assert asset.is_file(), f"README visual does not exist: {target}"
        assert 0 < asset.stat().st_size < 2_000_000, f"README visual is too large: {target}"

    ET.parse(  # noqa: S314 - this is a repository-owned static asset
        repository / "docs" / "assets" / "benchmark-pipeline.svg"
    )


def test_recommended_topics_are_focused_and_github_compatible() -> None:
    repository = Path(__file__).resolve().parents[1]
    metadata = (repository / "docs" / "repository-metadata.md").read_text(encoding="utf-8")
    topic_block = re.search(r"## Topics\s+```text\s+(.+?)```", metadata, re.DOTALL)

    assert topic_block is not None
    topics = topic_block.group(1).split()
    assert len(topics) <= 20
    assert len(topics) == len(set(topics))
    assert all(re.fullmatch(r"[a-z0-9-]{1,50}", topic) for topic in topics)
