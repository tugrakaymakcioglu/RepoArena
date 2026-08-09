from __future__ import annotations

from dataclasses import dataclass

from repoarena.benchmark.models import CommandSpec
from repoarena.config.models import VerificationConfig
from repoarena.git import GitRepository


@dataclass(frozen=True, slots=True)
class VerificationProfile:
    name: str
    image: str
    setup_commands: tuple[CommandSpec, ...]
    test_command: CommandSpec


def detect_profile(
    repository: GitRepository,
    base_commit: str,
    test_paths: tuple[str, ...],
    config: VerificationConfig,
) -> VerificationProfile | None:
    if config.profile == "custom":
        if config.image is None:
            return None
        return VerificationProfile(
            name="custom",
            image=config.image,
            setup_commands=tuple(CommandSpec(argv=command) for command in config.setup_commands),
            test_command=CommandSpec(argv=config.test_command),
        )
    if config.profile not in {"auto", "python", "node", "go"}:
        return None

    has_python = any(path.endswith(".py") for path in test_paths)
    if config.profile in {"auto", "python"} and has_python:
        setup = [CommandSpec(argv=["python", "-m", "venv", "/workspace/.repoarena-venv"])]
        python = "/workspace/.repoarena-venv/bin/python"
        if repository.file_exists(base_commit, "pyproject.toml") or repository.file_exists(
            base_commit, "setup.py"
        ):
            setup.append(CommandSpec(argv=[python, "-m", "pip", "install", "-e", "."]))
        elif repository.file_exists(base_commit, "requirements.txt"):
            setup.append(
                CommandSpec(argv=[python, "-m", "pip", "install", "-r", "requirements.txt"])
            )
        else:
            return None
        setup.append(CommandSpec(argv=[python, "-m", "pip", "install", "pytest"]))
        return VerificationProfile(
            name="python",
            image="python:3.12-slim",
            setup_commands=tuple(setup),
            test_command=CommandSpec(argv=[python, "-m", "pytest", "-q", *test_paths]),
        )

    has_node = any(path.endswith((".js", ".jsx", ".ts", ".tsx")) for path in test_paths)
    if (
        config.profile in {"auto", "node"}
        and has_node
        and repository.file_exists(base_commit, "package.json")
    ):
        if repository.file_exists(base_commit, "pnpm-lock.yaml"):
            node_setup = CommandSpec(argv=["corepack", "pnpm", "install", "--frozen-lockfile"])
            test = ["corepack", "pnpm", "test", "--", *test_paths]
        elif repository.file_exists(base_commit, "yarn.lock"):
            node_setup = CommandSpec(argv=["corepack", "yarn", "install", "--immutable"])
            test = ["corepack", "yarn", "test", *test_paths]
        else:
            node_setup = CommandSpec(argv=["npm", "ci"])
            test = ["npm", "test", "--", *test_paths]
        return VerificationProfile(
            name="node",
            image="node:22-bookworm-slim",
            setup_commands=(node_setup,),
            test_command=CommandSpec(argv=test),
        )

    has_go = any(path.endswith("_test.go") for path in test_paths)
    if (
        config.profile in {"auto", "go"}
        and has_go
        and repository.file_exists(base_commit, "go.mod")
    ):
        return VerificationProfile(
            name="go",
            image="golang:1.23-bookworm",
            setup_commands=(CommandSpec(argv=["go", "mod", "download"]),),
            test_command=CommandSpec(argv=["go", "test", "./..."]),
        )
    return None
