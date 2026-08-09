from repoarena.agents.cli import DockerCliAgent


class GeminiAgentRunner(DockerCliAgent):
    name = "gemini"
    credential_environment = "GEMINI_API_KEY"
    credential_target = "/home/node/.gemini/oauth_creds.json"

    def additional_environment(self) -> dict[str, str]:
        return {"GEMINI_CLI_TRUST_WORKSPACE": "true"}

    def command(self) -> list[str]:
        command = [
            self.config.executable,
            "--yolo",
            "--skip-trust",
            "--output-format",
            "stream-json",
        ]
        if self.config.model:
            command.extend(["--model", self.config.model])
        return command
