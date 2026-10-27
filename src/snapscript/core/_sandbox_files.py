"""Shared workspace preparation, destination guards, and atomic output commit."""

from collections.abc import Callable
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import time

import pandas as pd

from snapscript.config import AppConfig
from snapscript.core import schema_inspector
from snapscript.core.csv_io import read_csv_preview
from snapscript.core.models import ErrorCategory, ExecutionResult, InputFileSpec


class OutputValidationError(Exception):
    def __init__(self, message: str, category: ErrorCategory = "output_validation") -> None:
        super().__init__(message)
        self.category = category


def script_error_category(stderr: str) -> ErrorCategory:
    """Translate the generated-script validation protocol at the process boundary."""
    return "input_validation" if re.search(r"^ValueError: Input validation:", stderr, re.MULTILINE) else "sandbox_failure"


def validate_destination(
    inputs: Path | list[InputFileSpec], output_path: Path, *, overwrite: bool = True,
) -> str | None:
    specs = inputs if isinstance(inputs, list) else [InputFileSpec(name="input", path=inputs)]
    output = Path(output_path)
    try:
        for spec in specs:
            source = Path(spec.path)
            if output.resolve() == source.resolve() or (
                output.exists() and source.exists() and output.samefile(source)
            ):
                return f"Output would overwrite input '{spec.name}'; choose a different output path"
        if not overwrite and (output.exists() or output.is_symlink()):
            return "Output already exists; choose a new output path"
        if output.is_symlink() or (output.exists() and not output.is_file()):
            return "Output must be a regular file, not a symlink or directory"
        parent = output.parent
        while not (parent.exists() or parent.is_symlink()):
            parent = parent.parent
        with tempfile.NamedTemporaryFile(prefix=".snapscript-check-", dir=parent):
            pass
    except OSError:
        return "Output directory is not writable; choose a writable output path"
    return None


def validate_output(output_path: Path, max_size_bytes: int = 100 * 1024 * 1024) -> None:
    try:
        if output_path.is_symlink():
            raise OutputValidationError("Output must not be a symlink")
        if not output_path.exists():
            raise OutputValidationError("Output file was not created")
        if not output_path.is_file():
            raise OutputValidationError("Output is not a regular file")
        if output_path.stat().st_size == 0:
            raise OutputValidationError("Output is empty", "output_empty")
        if output_path.stat().st_size > max_size_bytes:
            raise OutputValidationError(f"Output exceeds size limit of {max_size_bytes} bytes", "output_limit")
        preview = (
            pd.read_excel(output_path, nrows=1)
            if output_path.suffix.lower() == ".xlsx"
            else read_csv_preview(output_path, nrows=1)
        )
    except OutputValidationError:
        raise
    except Exception as exc:
        raise OutputValidationError(f"Output unreadable: {exc}") from None
    if preview.empty:
        raise OutputValidationError("Output is empty", "output_empty")


def commit_output(source: Path, destination: Path, *, overwrite: bool) -> str | None:
    """Publish a complete file without following destination symlinks."""
    staged: Path | None = None
    error: str | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".snapscript-", dir=destination.parent, delete=False) as handle:
            staged = Path(handle.name)
        shutil.copyfile(source, staged)
        if overwrite:
            os.replace(staged, destination)
        else:
            os.link(staged, destination)
    except FileExistsError:
        error = "Output already exists; choose a new output path"
    except OSError:
        error = "Could not commit output file"
    finally:
        if staged is not None:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                error = error or "Could not remove staged output file"
    return error


def prepare_workspace(
    workspace: Path, code: str, inputs: list[InputFileSpec], output: Path, *,
    single_file: bool, container_root: str | None = None,
) -> Path:
    paths: dict[str, str] = {}
    for index, spec in enumerate(inputs):
        name = f"input{spec.path.suffix}" if single_file else f"input_{index}{spec.path.suffix}"
        copied = workspace / name
        shutil.copy2(spec.path, copied)
        paths[spec.name] = str(PurePosixPath(container_root) / name) if container_root else str(copied)
    temporary_output = workspace / f"output{output.suffix}"
    output_value = str(PurePosixPath(container_root) / temporary_output.name) if container_root else str(temporary_output)
    input_value = json.dumps(paths["input"]) if single_file else "None"
    (workspace / "_snapscript_paths.py").write_text(
        f"INPUT_PATH = {input_value}\nINPUT_PATHS = {json.dumps(paths, sort_keys=True)}\n"
        f"OUTPUT_PATH = {json.dumps(output_value)}\n", encoding="utf-8",
    )
    (workspace / "script.py").write_text(code, encoding="utf-8")
    if container_root:
        prepare_container_permissions(workspace)
    return temporary_output


def container_identity() -> tuple[int, int]:
    """Map a POSIX caller to a non-root numeric identity, including root callers."""
    uid, gid = os.geteuid(), os.getegid()
    return (1000, 1000) if uid == 0 else (uid, gid)


def prepare_container_permissions(workspace: Path) -> None:
    uid, gid = container_identity()
    if os.geteuid() == 0:
        os.chown(workspace, uid, gid)
    workspace.chmod(0o700)
    for child in workspace.iterdir():
        if child.is_file():
            if os.geteuid() == 0:
                os.chown(child, uid, gid)
            child.chmod(0o600)


def execute_in_workspace(
    code: str, inputs: list[InputFileSpec], output_path: Path, config: AppConfig,
    runner: Callable[[Path, AppConfig, float], ExecutionResult], *,
    single_file: bool, container_root: str | None = None,
) -> ExecutionResult:
    start = time.monotonic()
    try:
        inputs = schema_inspector.validate_input_specs(inputs)
    except schema_inspector.SchemaInspectionError as exc:
        return ExecutionResult(success=False, stderr=str(exc), exit_code=1, error_category="input_validation")
    error = validate_destination(inputs, output_path, overwrite=config.overwrite_output)
    if error:
        return ExecutionResult(success=False, stderr=error, exit_code=1, error_category="input_validation")
    try:
        with tempfile.TemporaryDirectory(prefix="snapscript_") as name:
            workspace = Path(name).resolve() / "workspace"
            workspace.mkdir(mode=0o700)
            temporary_output = prepare_workspace(
                workspace, code, inputs, output_path,
                single_file=single_file, container_root=container_root,
            )
            result = runner(workspace, config, start)
            if result.success:
                try:
                    validate_output(temporary_output, config.max_output_file_size_bytes)
                    error = commit_output(temporary_output, output_path, overwrite=config.overwrite_output)
                    if error:
                        result.success, result.stderr, result.error_category = False, error, "output_commit"
                    else:
                        result.output_files = [output_path]
                except OutputValidationError as exc:
                    result.success, result.stderr, result.error_category = False, str(exc), exc.category
            result.execution_time_seconds = time.monotonic() - start
            return result
    except OSError:
        return ExecutionResult(success=False, stderr="Could not prepare execution workspace", exit_code=1, error_category="workspace_failure")
