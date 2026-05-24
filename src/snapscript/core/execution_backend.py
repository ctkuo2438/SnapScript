'''
retry_handler.run(...)
  -> code_generator.generate(...)
  -> safety_checker.check(...)
  -> execution_backend.execute(...)
      -> sandbox_executor.execute(...) # subprocess backend
      -> docker_sandbox_executor.execute(...) # Docker backend
'''

from __future__ import annotations

from pathlib import Path

from snapscript.config import AppConfig
from snapscript.core import docker_sandbox_executor, sandbox_executor
from snapscript.core.models import ExecutionResult


def execute(
    code: str, # LLM-generated code to execute
    input_path: Path, # input CSV/Excel file path
    output_path: Path, # output CSV/Excel file path
    config: AppConfig | None = None,
) -> ExecutionResult:
    
    # determine which sandbox backend to use based on config, default to subprocess if not specified
    #   default is subprocess, can be switched to docker via SNAPSCRIPT_SANDBOX_BACKEND=docker
    selected_config = config if config is not None else AppConfig()
    backend = str(getattr(selected_config, "sandbox_backend", "")).strip().lower()

    if backend == "subprocess":
        return sandbox_executor.execute(code, input_path, output_path)
    if backend == "docker":
        return docker_sandbox_executor.execute(code, input_path, output_path)

    raise ValueError(f"Unsupported sandbox backend: {backend}")
