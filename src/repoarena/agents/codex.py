from repoarena.agents.cli import DockerCliAgent


class CodexAgentRunner(DockerCliAgent):
    name = "codex"
    credential_environment = "OPENAI_API_KEY"
    credential_target = "/home/node/.codex/auth.json"

    def command(self) -> list[str]:
        command = [
            self.config.executable,
            "exec",
            "--cd",
            "/workspace",
            "--ephemeral",
            "--json",
            "--color",
            "never",
            "--sandbox",
            "workspace-write",
        ]
        if self.config.model:
            command.extend(["--model", self.config.model])
        command.append("-")
        return command
