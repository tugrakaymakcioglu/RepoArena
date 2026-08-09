from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from repoarena.config.models import NetworkPolicy, SandboxConfig
from repoarena.exceptions import SandboxError
from repoarena.utils.process import run_process
from repoarena.utils.redaction import redact

_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class SandboxExecution:
    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


class DockerRunner:
    def __init__(self, config: SandboxConfig) -> None:
        self.config = config

    def daemon_ready(self) -> bool:
        return (
            run_process(
                ["docker", "info", "--format", "{{.ServerVersion}}"], check=False
            ).returncode
            == 0
        )

    def image_exists(self, image: str) -> bool:
        return run_process(["docker", "image", "inspect", image], check=False).returncode == 0

    def image_identity(self, image: str) -> str:
        result = run_process(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image], check=False
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise SandboxError(f"Required Docker image is missing: {image}")
        return result.stdout.strip()

    def pull_image(self, image: str) -> str:
        result = run_process(["docker", "pull", image], check=False)
        if result.returncode != 0:
            raise SandboxError(result.stderr.strip() or f"Could not pull Docker image: {image}")
        return self.image_identity(image)

    def executable_version(self, image: str, executable: str) -> str | None:
        with tempfile.TemporaryDirectory(prefix="repoarena-doctor-") as temporary:
            execution = self.run(
                image=image,
                workspace=Path(temporary),
                argv=[executable, "--version"],
                timeout_seconds=30,
                network_policy=NetworkPolicy.NONE,
                home_directory="/tmp",  # noqa: S108 - container path
            )
        if execution.returncode != 0:
            return None
        version = (execution.stdout.strip() or execution.stderr.strip()).splitlines()
        return version[0] if version else None

    def run(
        self,
        *,
        image: str,
        workspace: Path,
        argv: Sequence[str],
        timeout_seconds: int,
        network_policy: NetworkPolicy,
        allowed_domains: Sequence[str] = (),
        environment: Mapping[str, str] | None = None,
        input_text: str | None = None,
        credential_mount: tuple[Path, str] | None = None,
        home_directory: str = "/tmp",  # noqa: S108 - container path
    ) -> SandboxExecution:
        if not self.daemon_ready():
            raise SandboxError(
                "Docker daemon is not reachable. Start Docker and run `repoarena doctor`."
            )
        if not self.image_exists(image):
            raise SandboxError(f"Required Docker image is missing: {image}")
        if network_policy is NetworkPolicy.PROVIDER_ONLY:
            with self._provider_network(tuple(allowed_domains)) as (network, proxy):
                env = dict(environment or {})
                env.update({"HTTP_PROXY": proxy, "HTTPS_PROXY": proxy, "ALL_PROXY": proxy})
                return self._run_container(
                    image=image,
                    workspace=workspace,
                    argv=argv,
                    timeout_seconds=timeout_seconds,
                    network=network,
                    environment=env,
                    input_text=input_text,
                    credential_mount=credential_mount,
                    home_directory=home_directory,
                )
        network = "none" if network_policy is NetworkPolicy.NONE else "bridge"
        return self._run_container(
            image=image,
            workspace=workspace,
            argv=argv,
            timeout_seconds=timeout_seconds,
            network=network,
            environment=environment or {},
            input_text=input_text,
            credential_mount=credential_mount,
            home_directory=home_directory,
        )

    def _run_container(
        self,
        *,
        image: str,
        workspace: Path,
        argv: Sequence[str],
        timeout_seconds: int,
        network: str,
        environment: Mapping[str, str],
        input_text: str | None,
        credential_mount: tuple[Path, str] | None,
        home_directory: str,
    ) -> SandboxExecution:
        workspace = workspace.resolve()
        if not workspace.is_dir() or "," in str(workspace):
            raise SandboxError("Workspace mount path is invalid")
        home = PurePosixPath(home_directory)
        if not home.is_absolute() or ".." in home.parts or "\x00" in home_directory:
            raise SandboxError("Container home directory is invalid")
        name = f"repoarena-run-{uuid.uuid4().hex[:12]}"
        uid = os.getuid() if hasattr(os, "getuid") else 1000
        gid = os.getgid() if hasattr(os, "getgid") else 1000
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            network,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.config.pids_limit),
            "--cpus",
            str(self.config.cpus),
            "--memory",
            self.config.memory,
            "--user",
            f"{uid}:{gid}",
            "--workdir",
            "/workspace",
            "--mount",
            f"type=bind,src={workspace},dst=/workspace",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=268435456",  # noqa: S108 - container tmpfs
            "--env",
            f"HOME={home_directory}",
            "--env",
            "NO_COLOR=1",
        ]
        for key, value in sorted(environment.items()):
            if not _ENVIRONMENT_NAME.fullmatch(key) or "\x00" in value:
                raise SandboxError(f"Unsafe environment entry: {key}")
            command.extend(["--env", f"{key}={value}"])
        if credential_mount:
            source, target = credential_mount
            resolved_source = source.resolve()
            target_path = PurePosixPath(target)
            if (
                not resolved_source.is_file()
                or "," in str(resolved_source)
                or not target_path.is_absolute()
                or ".." in target_path.parts
                or "\x00" in target
            ):
                raise SandboxError("Credential mount is invalid")
            command.extend(["--mount", f"type=bind,src={resolved_source},dst={target},readonly"])
        command.extend([image, *argv])
        started = time.monotonic()
        try:
            result = run_process(
                command,
                input_text=input_text,
                timeout=timeout_seconds,
                check=False,
            )
            return SandboxExecution(
                returncode=result.returncode,
                stdout=redact(result.stdout, environment.values()),
                stderr=redact(result.stderr, environment.values()),
                duration_seconds=time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as exc:
            run_process(["docker", "rm", "-f", name], check=False)
            stdout = (
                exc.stdout.decode("utf-8", "replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")
            )
            stderr = (
                exc.stderr.decode("utf-8", "replace")
                if isinstance(exc.stderr, bytes)
                else (exc.stderr or "")
            )
            return SandboxExecution(
                returncode=None,
                stdout=redact(stdout, environment.values()),
                stderr=redact(stderr, environment.values()),
                duration_seconds=time.monotonic() - started,
                timed_out=True,
            )

    @contextmanager
    def _provider_network(self, allowed_domains: tuple[str, ...]) -> Iterator[tuple[str, str]]:
        if not allowed_domains:
            raise SandboxError("provider-only network requires at least one allowed domain")
        if not self.image_exists(self.config.proxy_image):
            raise SandboxError(
                f"Provider egress proxy image is missing: {self.config.proxy_image}. "
                "Build docker/sandbox/proxy.Dockerfile first."
            )
        network = f"repoarena-net-{uuid.uuid4().hex[:10]}"
        proxy_name = f"repoarena-proxy-{uuid.uuid4().hex[:10]}"
        temporary = Path(tempfile.mkdtemp(prefix="repoarena-proxy-"))
        config_path = temporary / "squid.conf"
        domains = " ".join(allowed_domains)
        config_path.write_text(
            "http_port 3128\n"
            "pid_filename none\n"
            "cache_log stdio:/dev/stderr\n"
            "coredump_dir /tmp\n"
            f"acl provider dstdomain {domains}\n"
            "acl SSL_ports port 443\n"
            "acl CONNECT method CONNECT\n"
            "http_access deny CONNECT !SSL_ports\n"
            "http_access allow provider\n"
            "http_access deny all\n"
            "access_log stdio:/dev/stdout\n"
            "cache deny all\n",
            encoding="utf-8",
        )
        try:
            run_process(["docker", "network", "create", "--internal", network])
            run_process(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    proxy_name,
                    "--network",
                    network,
                    "--network-alias",
                    "proxy",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    "128",
                    "--cpus",
                    "0.5",
                    "--memory",
                    "256m",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=67108864",  # noqa: S108 - container tmpfs
                    "--mount",
                    f"type=bind,src={config_path.resolve()},dst=/etc/squid/squid.conf,readonly",
                    self.config.proxy_image,
                ]
            )
            run_process(["docker", "network", "connect", "bridge", proxy_name])
            self._wait_for_proxy(proxy_name)
            yield network, "http://proxy:3128"
        finally:
            run_process(["docker", "rm", "-f", proxy_name], check=False)
            run_process(["docker", "network", "rm", network], check=False)
            import shutil

            shutil.rmtree(temporary, ignore_errors=True)

    @staticmethod
    def _wait_for_proxy(name: str) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            ready = run_process(
                [
                    "docker",
                    "exec",
                    name,
                    "squidclient",
                    "-h",
                    "127.0.0.1",
                    "-p",
                    "3128",
                    "mgr:info",
                ],
                check=False,
            )
            if ready.returncode == 0:
                return
            state = run_process(
                ["docker", "inspect", "--format", "{{.State.Running}}", name], check=False
            )
            if state.stdout.strip() != "true":
                break
            time.sleep(0.1)
        logs = run_process(["docker", "logs", name], check=False)
        detail = logs.stderr.strip() or logs.stdout.strip() or "no proxy diagnostics"
        raise SandboxError(f"Provider egress proxy did not become ready: {detail}")
