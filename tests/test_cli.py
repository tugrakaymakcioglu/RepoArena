from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoarena.cli.app import app
from repoarena.utils.process import run_process


def test_cli_init_and_benchmark_option_validation(monkeypatch: object, tmp_path: Path) -> None:
    run_process(["git", "init", "-b", "main"], cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    initialized = runner.invoke(app, ["init"])
    invalid_benchmark = runner.invoke(app, ["benchmark"])

    assert initialized.exit_code == 0
    assert "Repository and benchmark results stay on this machine" in initialized.stdout
    assert (tmp_path / ".repoarena" / "config.toml").is_file()
    assert invalid_benchmark.exit_code == 2
    assert "Choose exactly one" in invalid_benchmark.stdout
