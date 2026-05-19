from __future__ import annotations

from pathlib import Path

from snapscript.config import AppConfig
from snapscript.core import docker_sandbox_executor, sandbox_executor
from snapscript.core.models import ExecutionResult


def execute(
    code: str,
    input_path: Path,
    output_path: Path,
    config: AppConfig | None = None,
) -> ExecutionResult:
    selected_config = config if config is not None else AppConfig()
    backend = str(getattr(selected_config, "sandbox_backend", "")).strip().lower()

    if backend == "subprocess":
        return sandbox_executor.execute(code, input_path, output_path)
    if backend == "docker":
        return docker_sandbox_executor.execute(code, input_path, output_path)

    raise ValueError(f"Unsupported sandbox backend: {backend}")
