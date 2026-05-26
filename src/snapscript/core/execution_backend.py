'''Route generated code execution to the configured sandbox backend.'''

from __future__ import annotations

from pathlib import Path

from snapscript.config import AppConfig
from snapscript.core import docker_sandbox_executor, sandbox_executor
from snapscript.core.models import ExecutionResult, InputFileSpec


def execute(
    code: str, # LLM-generated code to execute
    input_path: Path | list[InputFileSpec], # input CSV/Excel file path or named input files
    output_path: Path, # output CSV/Excel file path
    config: AppConfig | None = None,
) -> ExecutionResult:
    
    # determine which sandbox backend to use based on config, default to subprocess if not specified
    #   default is subprocess, can be switched to docker via SNAPSCRIPT_SANDBOX_BACKEND=docker
    selected_config = config if config is not None else AppConfig()
    backend = str(getattr(selected_config, "sandbox_backend", "")).strip().lower()

    if backend == "subprocess":
        if isinstance(input_path, list):
            return sandbox_executor.execute_many(code, input_path, output_path)
        return sandbox_executor.execute(code, input_path, output_path)
    if backend == "docker":
        if isinstance(input_path, list):
            return docker_sandbox_executor.execute_many(code, input_path, output_path)
        return docker_sandbox_executor.execute(code, input_path, output_path)

    raise ValueError(f"Unsupported sandbox backend: {backend}")
