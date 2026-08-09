from __future__ import annotations

import json

from repoarena.agents.cli import DockerCliAgent
from repoarena.config.models import RouterAgentConfig
from repoarena.sandbox import DockerRunner


class OpenCodeRouterAgent(DockerCliAgent):
    """Run OpenCode against an isolated OpenAI-compatible routing endpoint."""

    credential_target = "/home/node/.local/share/opencode/auth.json"

    def __init__(
        self,
        name: str,
        config: RouterAgentConfig,
        docker: DockerRunner,
    ) -> None:
        super().__init__(config, docker)
        self.name = name
        self.router_config = config
        self.credential_environment = config.api_key_env

    def additional_environment(self) -> dict[str, str]:
        model = self.router_config.model
        if model is None:
            return {}
        provider = self.router_config.provider_id
        configuration = {
            "$schema": "https://opencode.ai/config.json",
            "autoupdate": False,
            "share": "disabled",
            "snapshot": False,
            "default_agent": "build",
            "permission": {
                "*": "allow",
                "external_directory": "deny",
                "question": "deny",
                "webfetch": "deny",
                "websearch": "deny",
            },
            "provider": {
                provider: {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": f"RepoArena {self.name}",
                    "options": {
                        "baseURL": self.router_config.base_url,
                        "apiKey": f"{{env:{self.router_config.api_key_env}}}",
                    },
                    "models": {model: {"name": model, "tool_call": True}},
                }
            },
        }
        return {
            "OPENCODE_AUTO_SHARE": "false",
            "OPENCODE_DISABLE_AUTOUPDATE": "true",
            "OPENCODE_CONFIG_CONTENT": json.dumps(
                configuration, ensure_ascii=True, separators=(",", ":")
            ),
        }

    def command(self) -> list[str]:
        command = [self.config.executable, "--pure", "run", "--format", "json"]
        if self.router_config.model:
            command.extend(
                ["--model", f"{self.router_config.provider_id}/{self.router_config.model}"]
            )
        command.append("Follow the complete task supplied through standard input.")
        return command
