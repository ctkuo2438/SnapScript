"""Route execution to one of the two existing sandbox backends."""

from pathlib import Path

from snapscript.config import AppConfig
from snapscript.core import _docker_runtime, docker_sandbox_executor, sandbox_executor
from snapscript.core.models import ExecutionResult, InputFileSpec


def preflight(config: AppConfig) -> ExecutionResult | None:
    if config.sandbox_backend == "docker":
        return _docker_runtime.preflight(config)
    return None


def execute(
    code: str, input_path: Path | list[InputFileSpec], output_path: Path,
    config: AppConfig | None = None,
) -> ExecutionResult:
    selected = config or AppConfig()
    backends = {"subprocess": sandbox_executor, "docker": docker_sandbox_executor}
    backend = backends.get(str(selected.sandbox_backend).strip().lower())
    if backend is None:
        raise ValueError(f"Unsupported sandbox backend: {selected.sandbox_backend}")
    if isinstance(input_path, list):
        return backend.execute_many(code, input_path, output_path, config=selected)
    return backend.execute(code, input_path, output_path, config=selected)
