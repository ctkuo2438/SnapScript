'''
schema_inspector.inspect(...)
  -> prompt_builder.build(...)
  -> retry_handler.run(...)
      -> execution_backend.execute(...)
          -> sandbox_executor.execute(...) # subprocess backend
          -> docker_sandbox_executor.execute(...) # Docker backend

when the config is SNAPSCRIPT_SANDBOX_BACKEND=docker
'''

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pandas as pd

from snapscript.config import AppConfig
from snapscript.core.models import ExecutionResult, InputFileSpec


SCRIPT_NAME = "script.py"
PATHS_MODULE_NAME = "_snapscript_paths.py"
# DEFAULT_DOCKER_IMAGE = "snapscript-sandbox:local"
CONTAINER_WORKDIR = "/workspace"
DOCKER_PIDS_LIMIT = "128"
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def execute(code: str, input_path: Path, output_path: Path) -> ExecutionResult:
    input_spec = InputFileSpec(name="input", path=Path(input_path))
    return _execute_with_inputs(code, [input_spec], Path(output_path), single_file=True)


def execute_many(
    code: str,
    inputs: list[InputFileSpec],
    output_path: Path,
) -> ExecutionResult:
    return _execute_with_inputs(code, inputs, Path(output_path), single_file=False)


def _execute_with_inputs(
    code: str,
    inputs: list[InputFileSpec],
    output_path: Path,
    single_file: bool,
) -> ExecutionResult:
    config = AppConfig()
    start_time = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="snapscript_docker_") as workspace_name:
        workspace = Path(workspace_name).resolve()
        if single_file:
            temp_input_path = _copy_input_to_workspace(inputs[0].path, workspace)
            copied_inputs = {"input": temp_input_path}
        else:
            temp_input_path = None
            copied_inputs = _copy_inputs_to_workspace(inputs, workspace)
        temp_output_path = workspace / _temp_output_name(output_path)

        _write_paths_module(workspace, temp_input_path, temp_output_path, copied_inputs) # container paths
        _write_script(workspace, code)
        # chmod workspace/files for non-root user in docker to read/write/execute
        _prepare_workspace_permissions(workspace)

        result = _run_docker(workspace, config, start_time)
        if not result.success:
            return result

        validation_error = _validate_and_copy_output(
            temp_output_path,
            Path(output_path),
        )
        if validation_error is not None:
            return _failure_result(
                stderr=validation_error,
                exit_code=result.exit_code,
                stdout=result.stdout,
                duration=_duration(start_time),
            )

        # successfully validated and copied output to requested location, 
        #   return success result with stdout and stderr from docker execution
        requested_output_path = Path(output_path)
        return ExecutionResult(
            success=True,
            stdout=result.stdout,
            stderr=result.stderr,
            output_files=[requested_output_path],
            execution_time_seconds=_duration(start_time),
            exit_code=result.exit_code,
        )


def _copy_input_to_workspace(input_path: Path, workspace: Path) -> Path:
    temp_input_path = workspace / f"input{Path(input_path).suffix}"
    shutil.copy2(input_path, temp_input_path)
    return temp_input_path


def _copy_inputs_to_workspace(
    inputs: list[InputFileSpec],
    workspace: Path,
) -> dict[str, Path]:
    copied_inputs: dict[str, Path] = {}
    for index, input_spec in enumerate(inputs):
        temp_input_path = workspace / _safe_input_filename(index, input_spec)
        shutil.copy2(input_spec.path, temp_input_path)
        copied_inputs[input_spec.name] = temp_input_path
    return copied_inputs


def _write_paths_module(
    workspace: Path,
    input_path: Path | None,
    output_path: Path,
    input_paths: dict[str, Path] | None = None,
) -> None:
    if input_path is None:
        input_path_content = "None"
        input_paths_content = json.dumps(
            {
                name: _container_path(path)
                for name, path in (input_paths or {}).items()
            },
            sort_keys=True,
        )
    else:
        input_path_content = json.dumps(_container_path(input_path))
        input_paths_content = '{"input": INPUT_PATH}'

    content = (
        f"INPUT_PATH = {input_path_content}\n"
        f"INPUT_PATHS = {input_paths_content}\n"
        f"OUTPUT_PATH = {json.dumps(_container_path(output_path))}\n"
    )
    (workspace / PATHS_MODULE_NAME).write_text(content, encoding="utf-8")


def _safe_input_filename(index: int, input_spec: InputFileSpec) -> str:
    source_name = Path(input_spec.display_filename or input_spec.path.name).name
    safe_source_name = SAFE_FILENAME_PATTERN.sub("_", source_name).strip("._")
    if not safe_source_name:
        safe_source_name = f"input{Path(input_spec.path).suffix}"
    safe_logical_name = SAFE_FILENAME_PATTERN.sub("_", input_spec.name).strip("._")
    return f"input_{index}_{safe_logical_name}_{safe_source_name}"


def _write_script(workspace: Path, code: str) -> None:
    (workspace / SCRIPT_NAME).write_text(code, encoding="utf-8")


# chmod workspace/files for non-root user in docker to read/write/execute
def _prepare_workspace_permissions(workspace: Path) -> None:
    workspace.chmod(0o777) # workspace directory, 0o777: read/write/execute for owner/group/others
    for child in workspace.iterdir():
        if child.is_file():
            child.chmod(0o666) # direct files, 0o666: read/write for owner/group/others


'''
Ex:
docker run --rm --memory 512m --cpus 0.5 --pids-limit 128 -v /tmp/snapscript_docker_abc123:/workspace -w /workspace snapscript-sandbox:local python script.py
'''
def _build_docker_command(workspace: Path, config: AppConfig) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
    ]
    # if disable docker network for better security, add --network none to the command
    if config.docker_network_disabled:
        command.extend(["--network", "none"])

    command.extend(
        [
            "--memory",
            config.docker_memory_limit,
            "--cpus",
            config.docker_cpu_limit,
            "--pids-limit",
            DOCKER_PIDS_LIMIT,
            "-v",
            f"{workspace.resolve()}:{CONTAINER_WORKDIR}",
            "-w",
            CONTAINER_WORKDIR,
            config.docker_image,
            "python",
            SCRIPT_NAME,
        ]
    )
    return command


def _run_docker(workspace: Path, config: AppConfig, start_time: float,) -> ExecutionResult:
    command = _build_docker_command(workspace, config)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=config.docker_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        message = (
            f"Docker execution timed out after "
            f"{config.docker_timeout_seconds} seconds"
        )
        if stderr:
            message = f"{message}\n{stderr}"
        return _failure_result(
            stderr=message,
            exit_code=-1,
            stdout=stdout,
            duration=_duration(start_time),
        )
    # if user doesn't have docker intalled or shell cannot find docker executable, 
    #   return failure result with error message
    except FileNotFoundError as exc:
        return _failure_result(
            stderr=f"Docker executable not found: {exc}",
            exit_code=127,
            stdout="",
            duration=_duration(start_time),
        )

    if completed.returncode != 0:
        return _failure_result(
            stderr=completed.stderr,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            duration=_duration(start_time),
        )

    return ExecutionResult(
        success=True,
        stdout=completed.stdout,
        stderr=completed.stderr,
        execution_time_seconds=_duration(start_time),
        exit_code=completed.returncode,
    )


def _validate_and_copy_output(temp_output_path: Path, requested_output_path: Path) -> str | None:
    validation_error = _validate_output(temp_output_path)
    if validation_error is not None:
        return validation_error

    requested_output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(temp_output_path, requested_output_path)
    return None


def _validate_output(output_path: Path) -> str | None:
    if not output_path.exists():
        return "Output file was not created"
    if output_path.stat().st_size == 0:
        return "Output is empty"

    try:
        if output_path.suffix.lower() in {".xlsx", ".xls"}:
            preview = pd.read_excel(output_path, nrows=1)
        else:
            preview = pd.read_csv(output_path, nrows=1)
    except Exception as exc:
        return f"Output unreadable: {exc}"

    if preview.empty:
        return "Output is empty"
    return None


def _temp_output_name(output_path: Path) -> str:
    suffix = output_path.suffix
    if suffix:
        return f"output{suffix}"
    return "output"


def _container_path(path: Path) -> str:
    return f"{CONTAINER_WORKDIR}/{path.name}"


def _failure_result(stderr: str, exit_code: int, stdout: str, duration: float) -> ExecutionResult:
    return ExecutionResult(
        success=False,
        stdout=stdout,
        stderr=stderr,
        output_files=[],
        execution_time_seconds=duration,
        exit_code=exit_code,
    )


def _duration(start_time: float) -> float:
    return time.monotonic() - start_time
