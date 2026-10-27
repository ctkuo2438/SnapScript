"""Docker execution using the shared workspace and output lifecycle."""

from pathlib import Path

from snapscript.config import AppConfig
from snapscript.core._docker_runtime import CONTAINER_WORKDIR, run as _run_docker
from snapscript.core._sandbox_files import execute_in_workspace
from snapscript.core.models import ExecutionResult, InputFileSpec


def execute(
    code: str, input_path: Path, output_path: Path, config: AppConfig | None = None,
) -> ExecutionResult:
    return execute_in_workspace(
        code, [InputFileSpec(name="input", path=Path(input_path))], Path(output_path),
        config or AppConfig(), _run_docker, single_file=True, container_root=CONTAINER_WORKDIR,
    )


def execute_many(
    code: str, inputs: list[InputFileSpec], output_path: Path, config: AppConfig | None = None,
) -> ExecutionResult:
    return execute_in_workspace(
        code, inputs, Path(output_path), config or AppConfig(), _run_docker,
        single_file=False, container_root=CONTAINER_WORKDIR,
    )
