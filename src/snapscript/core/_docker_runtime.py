"""Bounded Docker execution and cleanup of this run's container."""

import subprocess
import time
import uuid
from pathlib import Path

from snapscript.config import AppConfig
from snapscript.core.models import ExecutionResult


CONTAINER_WORKDIR = "/workspace"
MAX_EXECUTION_SECONDS = 30
CLEANUP_TIMEOUT_SECONDS = 5


def build_command(workspace: Path, config: AppConfig) -> list[str]:
    if not config.docker_network_disabled:
        raise ValueError("Docker sandbox requires disabled network access")
    return [
        "docker", "run", "--rm", "--name", f"snapscript-{uuid.uuid4().hex}",
        "--network", "none",
        "--memory", config.docker_memory_limit,
        "--cpus", config.docker_cpu_limit,
        "--pids-limit", "128",
        "-v", f"{workspace.resolve()}:{CONTAINER_WORKDIR}",
        "-w", CONTAINER_WORKDIR,
        config.docker_image, "python", "script.py",
    ]


def run(workspace: Path, config: AppConfig, start_time: float) -> ExecutionResult:
    try:
        command = build_command(workspace, config)
    except ValueError as exc:
        return ExecutionResult(success=False, stderr=str(exc), exit_code=1)
    timeout = min(config.docker_timeout_seconds, MAX_EXECUTION_SECONDS)
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        name = command[command.index("--name") + 1]
        cleanup_error = _remove_container(name)
        stderr = f"Docker execution timed out after {timeout} seconds"
        if isinstance(exc.stderr, str) and exc.stderr:
            stderr += f"\n{exc.stderr}"
        if cleanup_error:
            stderr += f"\n{cleanup_error}"
        return ExecutionResult(
            success=False, exit_code=-1, stderr=stderr,
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            execution_time_seconds=time.monotonic() - start_time,
        )
    except FileNotFoundError:
        return ExecutionResult(success=False, stderr="Docker executable not found", exit_code=127)
    return ExecutionResult(
        success=completed.returncode == 0,
        stdout=completed.stdout, stderr=completed.stderr, exit_code=completed.returncode,
        execution_time_seconds=time.monotonic() - start_time,
    )


def _remove_container(name: str) -> str | None:
    try:
        completed = subprocess.run(
            ["docker", "rm", "--force", name], capture_output=True, text=True,
            timeout=CLEANUP_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "Container cleanup failed; Docker could not confirm removal"
    if completed.returncode != 0 and "No such container" not in completed.stderr:
        return "Container cleanup failed; Docker could not confirm removal"
    return None
