from __future__ import annotations

from collections.abc import MutableMapping
from io import BytesIO
from pathlib import Path, PureWindowsPath
import re
import tempfile
import time

import pandas as pd
import streamlit as st

from snapscript.core import prompt_builder, retry_handler, schema_inspector
from snapscript.core.models import ExecutionResult


MAX_RUNS_PER_SESSION = 10
COOLDOWN_SECONDS = 5
ALLOWED_UPLOAD_SUFFIXES = {".csv", ".xlsx", ".xls"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
PREVIEW_MAX_ROWS = 100
ERROR_MAX_CHARS = 2000
GENERIC_ERROR_MESSAGE = "Something went wrong."
PROVIDER_ERROR_MESSAGE = (
    "Provider call failed. Check your API key or provider configuration."
)
SAFETY_ERROR_MESSAGE = "Generated code was rejected by the safety checker."
SANDBOX_ERROR_MESSAGE = "Execution failed in the sandbox."
DOWNLOAD_MIME_TYPES = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}

SESSION_DEFAULTS: dict[str, object] = {
    "uploaded_file_name": None,
    "uploaded_file_bytes": None,
    "uploaded_file_suffix": None,
    "task_text": "",
    "result_preview": None,
    "output_bytes": None,
    "output_file_name": None,
    "error_message": None,
    "run_count": 0,
    "last_run_timestamp": None,
    "is_running": False,
}


def initialize_session_state(
    state: MutableMapping[str, object] | None = None,
) -> None:
    target = st.session_state if state is None else state
    for key, default in SESSION_DEFAULTS.items():
        target.setdefault(key, default)


def clear_output_state(state: MutableMapping[str, object]) -> None:
    state["result_preview"] = None
    state["output_bytes"] = None
    state["output_file_name"] = None


def begin_accepted_run(
    state: MutableMapping[str, object],
    now: float | None = None,
) -> None:
    state["error_message"] = None
    clear_output_state(state)
    state["is_running"] = True
    if now is not None:
        state["run_count"] = int(state.get("run_count", 0)) + 1
        state["last_run_timestamp"] = now


def mark_run_success(
    state: MutableMapping[str, object],
    preview: pd.DataFrame,
    output_bytes: bytes,
    output_file_name: str,
) -> None:
    state["result_preview"] = preview
    state["output_bytes"] = output_bytes
    state["output_file_name"] = output_file_name
    state["error_message"] = None
    state["is_running"] = False


def mark_run_failure(
    state: MutableMapping[str, object],
    error_message: str,
) -> None:
    clear_output_state(state)
    state["error_message"] = error_message
    state["is_running"] = False


def mark_validation_error(
    state: MutableMapping[str, object],
    error_message: str,
) -> None:
    state["error_message"] = error_message
    state["is_running"] = False


def get_remaining_runs(
    run_count: int,
    max_runs: int = MAX_RUNS_PER_SESSION,
) -> int:
    return max(0, max_runs - run_count)


def check_rate_limit(
    run_count: int,
    last_run_timestamp: float | None,
    now: float,
    max_runs: int = MAX_RUNS_PER_SESSION,
    cooldown_seconds: int = COOLDOWN_SECONDS,
) -> tuple[bool, str | None]:
    if run_count >= max_runs:
        return False, "Run limit reached for this session."

    if last_run_timestamp is not None:
        elapsed = now - last_run_timestamp
        remaining = cooldown_seconds - elapsed
        if remaining > 0:
            return False, f"Please wait {remaining:.1f}s before running again."

    return True, None


def redact_error_text(message: str) -> str:
    redacted = re.sub(
        r"\b(?P<name>[A-Z0-9_]*(?:API[_-]?KEY|TOKEN|PASSWORD|SECRET))"
        r"\s*=\s*['\"]?[^\s'\",;]+['\"]?",
        lambda match: f"{match.group('name')}=[REDACTED]",
        message,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"\b(?P<name>api[_-]?key|token|password|secret)"
        r"\s*=\s*['\"]?[^\s'\",;]+['\"]?",
        lambda match: f"{match.group('name')}=[REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"\bBearer\s+sk-[A-Za-z0-9._-]+",
        "Bearer [REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"\bsk-ant-[A-Za-z0-9._-]+",
        "[REDACTED]",
        redacted,
    )
    redacted = re.sub(
        r"\bsk-[A-Za-z0-9][A-Za-z0-9._-]{8,}",
        "[REDACTED]",
        redacted,
    )
    return redacted


def truncate_error_text(
    message: str,
    max_chars: int = ERROR_MAX_CHARS,
) -> str:
    if len(message) <= max_chars:
        return message
    return f"{message[:max_chars]}... [truncated]"


def _strip_traceback_noise(message: str) -> str:
    lines = message.splitlines()
    if not any(line.strip().startswith("Traceback") for line in lines):
        return message.strip()

    useful_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Traceback"):
            continue
        if stripped.startswith("File "):
            continue
        if stripped.startswith("^"):
            continue
        if stripped.startswith("During handling"):
            continue
        if stripped.startswith("The above exception"):
            continue
        useful_lines.append(stripped)

    return useful_lines[-1] if useful_lines else GENERIC_ERROR_MESSAGE


def _redact_internal_paths(message: str) -> str:
    return re.sub(
        r"(?:(?:/private)?/tmp|/var/folders)/[^\s'\",;:]+",
        "[path]",
        message,
    )


def format_user_error(
    message: str | None,
    max_chars: int | None = None,
) -> str:
    text = "" if message is None else str(message).strip()
    if not text:
        return GENERIC_ERROR_MESSAGE

    text = _strip_traceback_noise(text)
    text = redact_error_text(text)
    text = _redact_internal_paths(text)
    if not text.strip():
        text = GENERIC_ERROR_MESSAGE
    limit = ERROR_MAX_CHARS if max_chars is None else max_chars
    return truncate_error_text(text, limit)


def _is_provider_error(message: str) -> bool:
    lower = message.lower()
    provider_indicators = (
        "providercallerror",
        "provider call failed",
        "api_key",
        "api key",
        "authentication",
        "unauthorized",
        "forbidden",
        "401",
        "403",
    )
    return any(indicator in lower for indicator in provider_indicators)


def _is_safety_error(message: str) -> bool:
    lower = message.lower()
    return "safety" in lower or "unsafe" in lower


def _format_pipeline_error(
    message: str | None,
    exit_code: int | None = None,
    default_to_sandbox: bool = False,
) -> str:
    raw_message = "" if message is None else str(message)
    if _is_provider_error(raw_message):
        return PROVIDER_ERROR_MESSAGE
    if _is_safety_error(raw_message):
        return SAFETY_ERROR_MESSAGE

    safe_summary = format_user_error(raw_message)
    if default_to_sandbox and safe_summary != GENERIC_ERROR_MESSAGE:
        return format_user_error(
            f"{SANDBOX_ERROR_MESSAGE} Summary: {safe_summary}"
        )
    if default_to_sandbox or exit_code:
        return SANDBOX_ERROR_MESSAGE
    return safe_summary


def normalize_task_text(task_text: str) -> str:
    return task_text.strip()


def validate_task_text(task_text: str) -> str:
    normalized = normalize_task_text(task_text)
    if not normalized:
        raise ValueError("Task description is required.")
    return normalized


def can_generate(
    state: MutableMapping[str, object],
) -> tuple[bool, str | None]:
    if (
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


def validate_upload_suffix(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        display_suffix = suffix or "missing extension"
        raise ValueError(f"Unsupported file type: {display_suffix}")
    return suffix


def validate_upload_size(size_or_bytes: int | bytes) -> None:
    size = (
        len(size_or_bytes)
        if isinstance(size_or_bytes, bytes)
        else size_or_bytes
    )
    if size > MAX_UPLOAD_BYTES:
        raise ValueError("Upload is too large. Maximum size is 10 MB.")


def store_uploaded_file(
    state: MutableMapping[str, object],
    file_name: str,
    file_bytes: bytes,
) -> None:
    try:
        suffix = validate_upload_suffix(file_name)
        validate_upload_size(file_bytes)
    except ValueError as exc:
        state["uploaded_file_name"] = None
        state["uploaded_file_bytes"] = None
        state["uploaded_file_suffix"] = None
        state["error_message"] = str(exc)
        raise

    state["uploaded_file_name"] = file_name
    state["uploaded_file_bytes"] = file_bytes
    state["uploaded_file_suffix"] = suffix
    state["error_message"] = None


def write_upload_to_temp_input(
    temp_dir: Path,
    file_bytes: bytes,
    suffix: str,
) -> Path:
    normalized_suffix = validate_upload_suffix(f"input{suffix}")
    temp_root = temp_dir.resolve()
    input_path = (temp_root / f"input{normalized_suffix}").resolve()
    if input_path.parent != temp_root:
        raise ValueError("Temporary input path must stay inside temp_dir.")
    input_path.write_bytes(file_bytes)
    return input_path


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


def load_output_preview(
    output_bytes: bytes,
    suffix: str,
    max_rows: int = PREVIEW_MAX_ROWS,
) -> pd.DataFrame:
    normalized_suffix = validate_upload_suffix(f"output{suffix}")
    buffer = BytesIO(output_bytes)
    try:
        if normalized_suffix == ".csv":
            return pd.read_csv(buffer, nrows=max_rows)
        return pd.read_excel(buffer, nrows=max_rows)
    except Exception as exc:
        raise ValueError("Could not read output preview.") from exc


def download_mime_type(suffix: str) -> str:
    normalized_suffix = validate_upload_suffix(f"output{suffix}")
    return DOWNLOAD_MIME_TYPES[normalized_suffix]


def run_uploaded_task(
    uploaded_file_bytes: bytes,
    upload_suffix: str,
    task_text: str,
    uploaded_file_name: str | None = None,
) -> tuple[ExecutionResult, bytes | None, str | None]:
    normalized_suffix = validate_upload_suffix(f"input{upload_suffix}")
    normalized_task = validate_task_text(task_text)

    with tempfile.TemporaryDirectory(prefix="snapscript_web_") as temp_name:
        temp_dir = Path(temp_name).resolve()
        input_path = write_upload_to_temp_input(
            temp_dir,
            uploaded_file_bytes,
            normalized_suffix,
        )
        output_path = temp_dir / f"output{normalized_suffix}"

        schema = schema_inspector.inspect(input_path)
        prompt = prompt_builder.build(normalized_task, schema)
        result = retry_handler.run(prompt, input_path, output_path)

        if not result.success:
            return result, None, None

        return (
            result,
            output_path.read_bytes(),
            derive_output_file_name(uploaded_file_name, normalized_suffix),
        )


def format_execution_error(result: ExecutionResult) -> str:
    message = result.stderr.strip() or result.stdout.strip()
    if not message:
        return "Execution failed."
    return _format_pipeline_error(
        message,
        exit_code=result.exit_code,
        default_to_sandbox=True,
    )


def format_exception_error(exc: Exception) -> str:
    return _format_pipeline_error(
        f"{type(exc).__name__}: {exc}",
        default_to_sandbox=False,
    )


def main() -> None:
    initialize_session_state()

    st.title("SnapScript")
    st.write("Transform a CSV or Excel file with a natural-language task.")

    uploaded_file = st.file_uploader(
        "Upload CSV or Excel file",
        type=["csv", "xlsx", "xls"],
    )
    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        try:
            store_uploaded_file(
                st.session_state,
                uploaded_file.name,
                file_bytes,
            )
        except ValueError:
            pass
        else:
            st.success(
                f"Uploaded {uploaded_file.name} ({len(file_bytes)} bytes)."
            )

    task_text = st.text_area(
        "Describe the transformation",
        value=str(st.session_state["task_text"]),
    )
    st.session_state["task_text"] = task_text

    remaining_runs = get_remaining_runs(int(st.session_state["run_count"]))
    st.caption(f"Remaining runs this session: {remaining_runs}")

    can_run, disabled_reason = can_generate(st.session_state)
    if (
        not can_run
        and disabled_reason == "Run limit reached for this session."
    ):
        mark_validation_error(st.session_state, disabled_reason)

    if st.button("Generate", disabled=not can_run):
        can_run, validation_error = can_generate(st.session_state)
        if not can_run:
            mark_validation_error(
                st.session_state,
                validation_error or "Cannot generate.",
            )
        else:
            now = time.monotonic()
            last_run_timestamp = st.session_state["last_run_timestamp"]
            accepted, rate_limit_error = check_rate_limit(
                int(st.session_state["run_count"]),
                (
                    float(last_run_timestamp)
                    if last_run_timestamp is not None
                    else None
                ),
                now,
            )
            if not accepted:
                mark_validation_error(
                    st.session_state,
                    rate_limit_error or "Cannot generate.",
                )
            else:
                begin_accepted_run(st.session_state, now=now)
                try:
                    uploaded_file_name = st.session_state[
                        "uploaded_file_name"
                    ]
                    display_file_name = (
                        str(uploaded_file_name)
                        if uploaded_file_name is not None
                        else None
                    )
                    result, output_bytes, output_file_name = run_uploaded_task(
                        bytes(st.session_state["uploaded_file_bytes"]),
                        str(st.session_state["uploaded_file_suffix"]),
                        str(st.session_state["task_text"]),
                        uploaded_file_name=display_file_name,
                    )
                    if result.success and output_bytes is not None:
                        result_preview = load_output_preview(
                            output_bytes,
                            str(st.session_state["uploaded_file_suffix"]),
                        )
                except Exception as exc:
                    mark_run_failure(
                        st.session_state,
                        format_exception_error(exc),
                    )
                else:
                    if result.success:
                        if output_bytes is None or output_file_name is None:
                            mark_run_failure(
                                st.session_state,
                                "Output file was not available.",
                            )
                            st.error(str(st.session_state["error_message"]))
                        else:
                            mark_run_success(
                                st.session_state,
                                result_preview,
                                output_bytes,
                                output_file_name,
                            )
                            st.success("Generation succeeded.")
                    else:
                        mark_run_failure(
                            st.session_state,
                            format_execution_error(result),
                        )
                        st.error(str(st.session_state["error_message"]))

    st.subheader("Output")
    result_preview = st.session_state["result_preview"]
    if result_preview is not None:
        st.caption(f"Showing up to {PREVIEW_MAX_ROWS} preview rows.")
        st.dataframe(result_preview)
    else:
        st.info("Output preview will appear here after a successful run.")

    output_bytes = st.session_state["output_bytes"]
    output_file_name = st.session_state["output_file_name"]
    if output_bytes is not None and output_file_name is not None:
        st.download_button(
            label="Download output",
            data=output_bytes,
            file_name=str(output_file_name),
            mime=download_mime_type(Path(str(output_file_name)).suffix),
        )

    st.subheader("Errors")
    error_message = st.session_state["error_message"]
    if error_message:
        st.error(str(error_message))
    else:
        st.info("No errors.")
