from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path

import streamlit as st


MAX_RUNS_PER_SESSION = 10
ALLOWED_UPLOAD_SUFFIXES = {".csv", ".xlsx", ".xls"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

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


def get_remaining_runs(
    run_count: int,
    max_runs: int = MAX_RUNS_PER_SESSION,
) -> int:
    return max(0, max_runs - run_count)


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

    can_run, _disabled_reason = can_generate(st.session_state)
    if st.button("Generate", disabled=not can_run):
        can_run, validation_error = can_generate(st.session_state)
        if not can_run:
            st.session_state["error_message"] = validation_error
        else:
            st.session_state["error_message"] = None
            st.info("Generation is not wired yet. This is the Phase 2 skeleton.")

    st.subheader("Output")
    st.info("Output preview will appear here after generation is wired.")

    st.subheader("Errors")
    error_message = st.session_state["error_message"]
    if error_message:
        st.error(str(error_message))
    else:
        st.info("No errors.")
