"""Bounded Docker execution and cleanup of this run's container."""

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from snapscript.config import AppConfig
from snapscript.core.models import ExecutionResult
from snapscript.core._process import CaptureLimitExceeded, run_process
from snapscript.core._sandbox_files import container_identity, script_error_category


CONTAINER_WORKDIR = "/workspace"
CLEANUP_TIMEOUT_SECONDS = 5
PREFLIGHT_TIMEOUT_SECONDS = 5
SECCOMP_PROBE = (
    "from pathlib import Path; "
    "status = dict(line.split(':', 1) for line in "
    "Path('/proc/self/status').read_text().splitlines() if ':' in line); "
    "print(status.get('Seccomp', '').strip())"
)


def preflight(config: AppConfig) -> ExecutionResult | None:
    """Check local Docker readiness before any paid generation; never pull images."""
    if not config.docker_network_disabled:
        return _backend_failure("Docker sandbox requires disabled network access")
    if not hasattr(os, "geteuid") or not hasattr(os, "getegid"):
        return _backend_failure("Docker sandbox requires POSIX user mapping (macOS or Linux)")
    checks = [
        (["docker", "info", "--format", "{{json .SecurityOptions}}"],
         "Docker daemon is unavailable; start Docker and try again"),
        (["docker", "image", "inspect", "--format", "{{.Id}}", "--", config.docker_image],
         "Docker sandbox image is unavailable; build the configured image first"),
    ]
    for command, message in checks:
        try:
            result = run_process(command, timeout=PREFLIGHT_TIMEOUT_SECONDS, max_capture_bytes=4096)
        except FileNotFoundError:
            return _backend_failure("Docker executable not found", exit_code=127)
        except (OSError, subprocess.TimeoutExpired, CaptureLimitExceeded):
            return _backend_failure(message)
        if result.returncode != 0 or not result.stdout.strip():
            return _backend_failure(message)
        if command[1] == "info" and not _supports_seccomp(result.stdout):
            return _backend_failure("Docker seccomp support is unavailable; enable seccomp in Docker and try again")
    command = _container_options(config) + [config.docker_image, "python", "-c", SECCOMP_PROBE]
    probe = _run_command(command, PREFLIGHT_TIMEOUT_SECONDS, min(config.max_capture_bytes, 4096), time.monotonic())
    if probe.error_category == "timeout":
        _, _, cleanup_detail = probe.stderr.partition("\n")
        return _backend_failure(
            f"Docker security check timed out after {PREFLIGHT_TIMEOUT_SECONDS} seconds; "
            "make sure Docker is responsive and try again"
            + (f". {cleanup_detail}" if cleanup_detail else "")
        )
    if not probe.success or probe.stdout.strip() != "2":
        detail = f". {probe.stderr}" if probe.error_category == "capture_limit" else ""
        return _backend_failure(
            "Docker could not enforce the built-in seccomp profile; check Docker seccomp support and try again"
            + detail
        )
    return None


def _supports_seccomp(output: str) -> bool:
    try:
        options = json.loads(output)
    except (ValueError, TypeError):
        return False
    return isinstance(options, list) and any(
        isinstance(option, str) and option.split(",", 1)[0] == "name=seccomp"
        for option in options
    )


def _container_options(config: AppConfig) -> list[str]:
    if not config.docker_network_disabled:
        raise ValueError("Docker sandbox requires disabled network access")
    uid, gid = container_identity()
    return [
        "docker", "run", "--rm", "--pull", "never", "--name", f"snapscript-{uuid.uuid4().hex}",
        "--network", "none",
        "--memory", config.docker_memory_limit,
        "--cpus", config.docker_cpu_limit,
        "--pids-limit", "128",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--security-opt", "seccomp=builtin",
        "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777",
        "--user", f"{uid}:{gid}",
    ]


def build_command(workspace: Path, config: AppConfig) -> list[str]:
    return _container_options(config) + [
        "-v", f"{workspace.resolve()}:{CONTAINER_WORKDIR}",
        "-w", CONTAINER_WORKDIR,
        config.docker_image, "python", "script.py",
    ]


def run(workspace: Path, config: AppConfig, start_time: float) -> ExecutionResult:
    try:
        command = build_command(workspace, config)
    except ValueError as exc:
        return _backend_failure(str(exc), exit_code=1)
    return _run_command(command, config.docker_timeout_seconds, config.max_capture_bytes, start_time)


def _run_command(command: list[str], timeout: int, max_capture_bytes: int, start_time: float) -> ExecutionResult:
    try:
        completed = run_process(
            command, timeout=timeout, max_capture_bytes=max_capture_bytes,
        )
    except (CaptureLimitExceeded, subprocess.TimeoutExpired) as exc:
        name = command[command.index("--name") + 1]
        cleanup_error = _remove_container(name)
        timed_out = isinstance(exc, subprocess.TimeoutExpired)
        stderr = f"Docker execution timed out after {timeout} seconds" if timed_out else str(exc)
        if timed_out and isinstance(exc.stderr, str) and exc.stderr:
            stderr += f"\n{exc.stderr}"
        if cleanup_error:
            stderr += f"\n{cleanup_error}"
        return ExecutionResult(
            success=False, exit_code=-1 if timed_out else -2, stderr=stderr,
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            execution_time_seconds=time.monotonic() - start_time,
            error_category="timeout" if timed_out else "capture_limit",
        )
    except FileNotFoundError:
        return _backend_failure("Docker executable not found", exit_code=127)
    except OSError:
        return _backend_failure("Could not start Docker execution")
    return ExecutionResult(
        success=completed.returncode == 0,
        stdout=completed.stdout, stderr=completed.stderr, exit_code=completed.returncode,
        execution_time_seconds=time.monotonic() - start_time,
        error_category=(
            "backend_unavailable" if completed.returncode in {125, 126, 127}
            else script_error_category(completed.stderr) if completed.returncode else None
        ),
    )


def _backend_failure(message: str, exit_code: int = 125) -> ExecutionResult:
    return ExecutionResult(
        success=False, stderr=message, exit_code=exit_code, error_category="backend_unavailable",
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
