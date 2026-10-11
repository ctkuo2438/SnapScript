"""Shared availability check for explicitly requested real Docker tests."""

import shutil
import subprocess

import pytest

from snapscript.config import AppConfig


@pytest.fixture(scope="module")
def docker_config():
    if not shutil.which("docker"):
        pytest.skip("Docker executable is unavailable")
    config = AppConfig(sandbox_backend="docker", docker_memory_limit="512m", docker_cpu_limit="1.0")
    commands = [
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        ["docker", "image", "inspect", config.docker_image],
    ]
    for command in commands:
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pytest.skip("Docker daemon/image is unavailable; see docs/docker_sandbox.md")
        if completed.returncode:
            pytest.skip("Docker daemon/image is unavailable; see docs/docker_sandbox.md")
    return config
