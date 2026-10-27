"""Compatibility subprocess backend; host-file isolation requires Docker."""

import os
from pathlib import Path
import subprocess
import sys
import time

from snapscript.config import AppConfig
from snapscript.core._process import CaptureLimitExceeded, run_process
from snapscript.core._sandbox_files import execute_in_workspace, script_error_category
from snapscript.core.models import ExecutionResult, InputFileSpec


def execute(
    code: str, input_path: Path, output_path: Path, config: AppConfig | None = None,
) -> ExecutionResult:
    return execute_in_workspace(
        code, [InputFileSpec(name="input", path=Path(input_path))], Path(output_path),
        config or AppConfig(), _run_script, single_file=True,
    )


def execute_many(
    code: str, inputs: list[InputFileSpec], output_path: Path, config: AppConfig | None = None,
) -> ExecutionResult:
    return execute_in_workspace(
        code, inputs, Path(output_path), config or AppConfig(), _run_script, single_file=False,
    )


def _run_script(workspace: Path, config: AppConfig, start_time: float) -> ExecutionResult:
    try:
        completed = run_process(
            [sys.executable, "script.py"], cwd=workspace, env=_child_environment(),
            max_capture_bytes=config.max_capture_bytes,
            timeout=config.execution_timeout_seconds,
        )
    except CaptureLimitExceeded as exc:
        return ExecutionResult(success=False, stderr=str(exc), stdout=exc.stdout, exit_code=-2, error_category="capture_limit")
    except subprocess.TimeoutExpired as exc:
        return ExecutionResult(
            success=False, exit_code=-1,
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr=f"Execution timed out after {config.execution_timeout_seconds} seconds",
            execution_time_seconds=time.monotonic() - start_time,
            error_category="timeout",
        )
    except OSError:
        return ExecutionResult(success=False, stderr="Could not start Python execution", exit_code=1, error_category="backend_unavailable")
    return ExecutionResult(
        success=completed.returncode == 0, stdout=completed.stdout,
        stderr=completed.stderr, exit_code=completed.returncode,
        execution_time_seconds=time.monotonic() - start_time,
        error_category=script_error_category(completed.stderr) if completed.returncode else None,
    )


def _child_environment() -> dict[str, str]:
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL",
        "LC_CTYPE", "TZ", "TMPDIR", "TMP", "TEMP",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}
