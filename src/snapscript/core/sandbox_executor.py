from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd

from snapscript.config import AppConfig
from snapscript.core.models import ExecutionResult


SCRIPT_NAME = "script.py"
PATHS_MODULE_NAME = "_snapscript_paths.py"


def execute(code: str, input_path: Path, output_path: Path) -> ExecutionResult:
    config = AppConfig()
    start_time = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="snapscript_") as workspace_name:
        workspace = Path(workspace_name)
        temp_input_path = workspace / f"input{Path(input_path).suffix}"
        temp_output_path = workspace / _temp_output_name(Path(output_path))

        shutil.copy2(input_path, temp_input_path)
        _write_paths_module(workspace, temp_input_path, temp_output_path)
        _write_script(workspace, code)

        result = _run_script(workspace, config, start_time)
        if not result.success:
            return result

        validation_error = _validate_output(temp_output_path)
        if validation_error is not None:
            return _failure_result(
                stderr=validation_error,
                exit_code=result.exit_code,
                stdout=result.stdout,
                duration=_duration(start_time),
            )

        requested_output_path = Path(output_path)
        requested_output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(temp_output_path, requested_output_path)

        return ExecutionResult(
            success=True,
            stdout=result.stdout,
            stderr=result.stderr,
            output_files=[requested_output_path],
            execution_time_seconds=_duration(start_time),
            exit_code=result.exit_code,
        )


def _temp_output_name(output_path: Path) -> str:
    suffix = output_path.suffix
    if suffix:
        return f"output{suffix}"
    return "output"


def _write_paths_module(
    workspace: Path, input_path: Path, output_path: Path
) -> None:
    content = (
        f"INPUT_PATH = {json.dumps(str(input_path))}\n"
        f"OUTPUT_PATH = {json.dumps(str(output_path))}\n"
    )
    (workspace / PATHS_MODULE_NAME).write_text(content, encoding="utf-8")


def _write_script(workspace: Path, code: str) -> None:
    (workspace / SCRIPT_NAME).write_text(code, encoding="utf-8")


def _run_script(
    workspace: Path, config: AppConfig, start_time: float
) -> ExecutionResult:
    try:
        completed = subprocess.run(
            [sys.executable, SCRIPT_NAME],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=config.execution_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        message = (
            f"Execution timed out after {config.execution_timeout_seconds} seconds"
        )
        if stderr:
            message = f"{message}\n{stderr}"
        return _failure_result(
            stderr=message,
            exit_code=-1,
            stdout=stdout,
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


def _failure_result(
    stderr: str, exit_code: int, stdout: str, duration: float
) -> ExecutionResult:
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
