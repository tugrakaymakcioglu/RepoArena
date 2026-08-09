from repoarena.agents.cli import DockerCliAgent


class ClaudeAgentRunner(DockerCliAgent):
    name = "claude"
    credential_environment = "ANTHROPIC_API_KEY"
    credential_target = "/home/node/.claude/.credentials.json"

    def command(self) -> list[str]:
        command = [
            self.config.executable,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--no-session-persistence",
            "--bare",
            "--permission-mode",
            "bypassPermissions",
        ]
        if self.config.model:
            command.extend(["--model", self.config.model])
        return command
