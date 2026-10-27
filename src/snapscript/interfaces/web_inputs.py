"""Upload validation, temporary files, previews, and session-local schema reuse."""
from __future__ import annotations

from collections.abc import MutableMapping
from io import BytesIO
from pathlib import Path, PureWindowsPath
import re
import tempfile

import pandas as pd

from snapscript.config import AppConfig
from snapscript.core import schema_inspector
from snapscript.core.csv_io import read_csv_preview
from snapscript.core.models import ErrorCategory, InputFileSpec, InputValidationError, MultiFileSchemaReport, SchemaReport
from snapscript.interfaces.web_state import (
    ERROR_SOURCE_UPLOAD, ERROR_SOURCE_VALIDATION, INPUT_MODE_SINGLE, INPUT_MODE_TWO,
    MAX_RUNS_PER_SESSION, update_input_state,
)

class OutputPreviewError(ValueError):
    category: ErrorCategory = "output_validation"


ALLOWED_UPLOAD_SUFFIXES = {".csv", ".xlsx"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
PREVIEW_MAX_ROWS = 100
DOWNLOAD_MIME_TYPES = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def normalize_task_text(task_text: str) -> str:
    return task_text.strip()


def validate_task_text(task_text: str) -> str:
    normalized = normalize_task_text(task_text)
    if not normalized:
        raise InputValidationError("Task description is required.")
    return normalized


def clear_input_error_state(state: MutableMapping[str, object]) -> None:
    if "error_source" not in state or state.get("error_source") in {
        ERROR_SOURCE_UPLOAD,
        ERROR_SOURCE_VALIDATION,
    }:
        state["error_message"] = None
        state["error_source"] = None


def can_generate(
    state: MutableMapping[str, object],
) -> tuple[bool, str | None]:
    if str(state.get("input_mode", INPUT_MODE_SINGLE)) == INPUT_MODE_TWO:
        try:
            validate_two_file_upload_state(state)
        except ValueError as exc:
            return False, str(exc)
    elif (
        state.get("uploaded_file_bytes") is None
        or state.get("uploaded_file_suffix") is None
    ):
        return False, "Upload a CSV or Excel file before generating."

    try:
        validate_task_text(str(state.get("task_text", "")))
    except ValueError as exc:
        return False, str(exc)

    if int(state.get("run_count", 0)) >= MAX_RUNS_PER_SESSION:
        return False, "Run limit reached for this session."

    return True, None


def validate_two_file_upload_state(
    state: MutableMapping[str, object],
) -> list[InputFileSpec]:
    if (
        state.get("first_uploaded_file_bytes") is None
        or state.get("first_uploaded_file_suffix") is None
        or state.get("second_uploaded_file_bytes") is None
        or state.get("second_uploaded_file_suffix") is None
    ):
        raise InputValidationError("Upload both files before generating.")

    first_name = str(state.get("first_logical_name", ""))
    second_name = str(state.get("second_logical_name", ""))
    if not first_name.strip() or not second_name.strip():
        raise InputValidationError("Logical names are required for two-file mode.")

    try:
        return schema_inspector.validate_input_specs(
            [
                InputFileSpec(name=first_name, path=Path("first_input")),
                InputFileSpec(name=second_name, path=Path("second_input")),
            ]
        )
    except schema_inspector.SchemaInspectionError as exc:
        raise InputValidationError(str(exc)) from exc


def validate_upload_suffix(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        display_suffix = suffix or "missing extension"
        raise InputValidationError(f"Unsupported file type: {display_suffix}")
    return suffix


def validate_upload_size(size_or_bytes: int | bytes) -> None:
    size: int
    if isinstance(size_or_bytes, bytes):
        size = len(size_or_bytes)
    else:
        size = int(size_or_bytes)

    if size > MAX_UPLOAD_BYTES:
        raise InputValidationError("Upload is too large. Maximum size is 10 MB.")


def store_uploaded_file(
    state: MutableMapping[str, object], file_name: str, file_bytes: bytes,
) -> None:
    store_named_uploaded_file(state, "", file_name, file_bytes)


def store_named_uploaded_file(
    state: MutableMapping[str, object], prefix: str, file_name: str, file_bytes: bytes,
) -> None:
    prefix = f"{prefix}_" if prefix else ""
    name_key, bytes_key, suffix_key = (f"{prefix}uploaded_file_{field}" for field in ("name", "bytes", "suffix"))
    try:
        suffix = validate_upload_suffix(file_name)
        validate_upload_size(file_bytes)
    except ValueError as exc:
        update_input_state(state, **{name_key: None, bytes_key: None, suffix_key: None})
        state["error_message"], state["error_source"] = str(exc), ERROR_SOURCE_UPLOAD
        raise
    update_input_state(state, **{name_key: file_name, bytes_key: file_bytes, suffix_key: suffix})
    clear_input_error_state(state)


def write_upload_to_temp_input(temp_dir: Path, file_bytes: bytes, suffix: str) -> Path:
    suffix = validate_upload_suffix(f"input{suffix}")
    validate_upload_size(file_bytes)
    path = temp_dir.resolve() / f"input{suffix}"
    path.write_bytes(file_bytes)
    return path


def materialize_uploads(state: MutableMapping[str, object], directory: Path) -> list[InputFileSpec]:
    if state.get("input_mode", INPUT_MODE_SINGLE) == INPUT_MODE_SINGLE:
        if state.get("uploaded_file_bytes") is None or state.get("uploaded_file_suffix") is None:
            raise InputValidationError("Upload a CSV or Excel file before generating.")
        return [InputFileSpec("input", write_upload_to_temp_input(
            directory, bytes(state["uploaded_file_bytes"]), str(state["uploaded_file_suffix"]),
        ))]
    names = validate_two_file_upload_state(state)
    inputs = []
    for index, slot in enumerate(("first", "second")):
        data = bytes(state[f"{slot}_uploaded_file_bytes"])
        validate_upload_size(data)
        suffix = validate_upload_suffix(f"input{state[f'{slot}_uploaded_file_suffix']}")
        path = directory / f"input_{index}{suffix}"
        path.write_bytes(data)
        inputs.append(InputFileSpec(
            names[index].name, path,
            display_filename=state.get(f"{slot}_uploaded_file_name"),
        ))
    return inputs


def inspect_uploaded_schema(
    state: MutableMapping[str, object], config: AppConfig, inputs: list[InputFileSpec] | None = None,
) -> SchemaReport | MultiFileSchemaReport:
    single = state.get("input_mode", INPUT_MODE_SINGLE) == INPUT_MODE_SINGLE
    slots = ("",) if single else ("first_", "second_")
    signature = (
        single, config.max_input_file_size_bytes, config.schema_sample_rows,
        config.schema_inspect_rows, config.max_column_name_chars,
        tuple(tuple(state.get(f"{slot}{key}") for key in (
            "uploaded_file_name", "uploaded_file_bytes", "uploaded_file_suffix", "logical_name",
        )) for slot in slots),
    )
    cached = state.get("_schema_cache")
    if cached is not None and cached[0] == signature:
        return cached[1]
    if inputs is None:
        with tempfile.TemporaryDirectory(prefix="snapscript_web_schema_") as name:
            inputs = materialize_uploads(state, Path(name).resolve())
            schema = _inspect_inputs(inputs, single, config)
    else:
        schema = _inspect_inputs(inputs, single, config)
    state["_schema_cache"] = (signature, schema)
    return schema


def _inspect_inputs(
    inputs: list[InputFileSpec], single: bool, config: AppConfig,
) -> SchemaReport | MultiFileSchemaReport:
    if single:
        return schema_inspector.inspect(inputs[0].path, config=config)
    return schema_inspector.inspect_many(inputs, config=config)


def derive_output_file_name(
    uploaded_file_name: str | None,
    suffix: str,
) -> str:
    normalized_suffix = validate_upload_suffix(f"output{suffix}")
    fallback = f"snapscript_output{normalized_suffix}"
    if not uploaded_file_name:
        return fallback

    posix_name = Path(uploaded_file_name).name
    safe_name = PureWindowsPath(posix_name).name
    stem = PureWindowsPath(safe_name).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    if not safe_stem:
        return fallback
    return f"{safe_stem}_snapscript_output{normalized_suffix}"


def derive_multi_output_file_name() -> str:
    return "snapscript_output.csv"


def load_output_preview(
    output_bytes: bytes,
    suffix: str,
    max_rows: int = PREVIEW_MAX_ROWS,
) -> pd.DataFrame:
    normalized_suffix = validate_upload_suffix(f"output{suffix}")
    buffer = BytesIO(output_bytes)
    try:
        if normalized_suffix == ".csv":
            return read_csv_preview(output_bytes, nrows=max_rows)
        return pd.read_excel(buffer, nrows=max_rows)
    except Exception as exc:
        raise OutputPreviewError("Could not read output preview.") from exc


def download_mime_type(suffix: str) -> str:
    normalized_suffix = validate_upload_suffix(f"output{suffix}")
    return DOWNLOAD_MIME_TYPES[normalized_suffix]
