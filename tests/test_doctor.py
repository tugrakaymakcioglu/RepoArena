from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import tomli_w

from repoarena.config import initialize
from repoarena.config.models import RepoArenaConfig
from repoarena.doctor import CheckLevel, collect_checks


def test_doctor_checks_only_enabled_agents(monkeypatch: object, tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.test"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repository, check=True)
    (repository / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repository, check=True)
    paths, _ = initialize(repository)
    config = RepoArenaConfig()
    config.agents.codex.enabled = False
    config.agents.claude.enabled = False
    config.agents.gemini.enabled = True
    paths.config.write_text(
        tomli_w.dumps(config.model_dump(mode="json", exclude_none=True)),
        encoding="utf-8",
    )
    real_which = shutil.which
    monkeypatch.setattr(
        "repoarena.doctor.shutil.which",
        lambda name: "docker" if name == "docker" else real_which(name),
    )
    monkeypatch.setattr("repoarena.doctor.DockerRunner.daemon_ready", lambda self: False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    checks = collect_checks(paths)
    names = {check.name for check in checks}

    assert "Gemini image" in names
    assert "Gemini auth" in names
    assert "Codex image" not in names
    assert "Codex auth" not in names
    assert "Claude image" not in names
    assert "Claude auth" not in names
    assert next(check for check in checks if check.name == "Gemini auth").level is CheckLevel.ERROR
