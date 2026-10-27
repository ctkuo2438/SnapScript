"""Streamlit composition; input handling and pipeline work live in focused modules."""
from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import replace
import os
from pathlib import Path
import time
import streamlit as st

from snapscript.config import AppConfig
from snapscript.core.models import ErrorCategory, ExecutionResult, InputValidationError
from snapscript.interfaces import web_inputs, web_assistant, web_pipeline, web_audit
from snapscript.interfaces.errors import (
    exception_category, format_error, format_execution_error, format_exception_error,
)
from snapscript.interfaces.web_state import (
    INPUT_MODE_SINGLE, INPUT_MODE_TWO, MAX_RUNS_PER_SESSION,
    begin_accepted_run, check_rate_limit, get_remaining_runs,
    initialize_session_state as _initialize_session_state,
    mark_run_failure, mark_run_success, mark_validation_error, update_input_state,
)

SANDBOX_BACKEND_ENV = "SNAPSCRIPT_SANDBOX_BACKEND"
DOCKER_BACKEND_HINT = "SNAPSCRIPT_SANDBOX_BACKEND=docker uv run streamlit run app.py"
DOCKER_IMAGE_BUILD_HINT = "docker build -t snapscript-sandbox:local docker/sandbox"
SUBPROCESS_BACKEND_WARNING = (
    "Subprocess backend is not isolated: generated code can reach this computer's "
    "files and network. Upload only trusted, non-private files, or use Docker."
)


def default_web_config() -> AppConfig:
    """Streamlit runs uploads in Docker unless the backend is explicitly chosen."""
    config = AppConfig()
    if SANDBOX_BACKEND_ENV in os.environ:
        return config
    return replace(config, sandbox_backend="docker")


def initialize_session_state(
    state: MutableMapping[str, object] | None = None,
) -> None:
    target = st.session_state if state is None else state
    _initialize_session_state(target)


def render_runtime_sidebar(config: AppConfig) -> None:
    st.sidebar.subheader("Runtime")
    st.sidebar.write(f"Sandbox backend: {config.sandbox_backend}")
    if config.sandbox_backend == "docker":
        st.sidebar.caption("Build the sandbox image once:")
        st.sidebar.code(DOCKER_IMAGE_BUILD_HINT)
        return
    st.sidebar.warning(SUBPROCESS_BACKEND_WARNING)
    st.sidebar.caption("Use Docker backend:")
    st.sidebar.code(DOCKER_BACKEND_HINT)


def _render_uploaded_file(slot: str | None = None) -> str | None:
    state = st.session_state
    uploaded = st.file_uploader(
        f"{slot.title()} CSV or Excel file" if slot else "Upload CSV or Excel file",
        type=["csv", "xlsx"],
        key=f"{slot}_file" if slot else None,
    )
    if slot:
        name_key = f"{slot}_logical_name"
        logical_name = st.text_input(
            f"{slot.title()} logical name", value=str(state[name_key])
        )
        update_input_state(state, **{name_key: logical_name})
    if uploaded is None:
        prefix = f"{slot}_" if slot else ""
        update_input_state(state, **{
            f"{prefix}uploaded_file_name": None,
            f"{prefix}uploaded_file_bytes": None,
            f"{prefix}uploaded_file_suffix": None,
        })
        return None

    file_bytes = uploaded.getvalue()
    try:
        if slot:
            web_inputs.store_named_uploaded_file(state, slot, uploaded.name, file_bytes)
        else:
            web_inputs.store_uploaded_file(state, uploaded.name, file_bytes)
    except ValueError:
        return str(state["error_message"])
    st.success(f"Uploaded {uploaded.name} ({len(file_bytes)} bytes).")
    return None


def _render_input_controls() -> str | None:
    state = st.session_state
    input_mode = st.radio(
        "Input mode",
        [INPUT_MODE_SINGLE, INPUT_MODE_TWO],
        index=1 if state["input_mode"] == INPUT_MODE_TWO else 0,
    )
    update_input_state(state, input_mode=input_mode)
    current_input_error: str | None = None
    slots = ("first", "second") if state["input_mode"] == INPUT_MODE_TWO else (None,)
    for slot in slots:
        current_input_error = _render_uploaded_file(slot) or current_input_error
    task_text = st.text_area(
        "Describe the transformation", value=str(state["task_text"])
    )
    update_input_state(state, task_text=task_text)
    return current_input_error


def _run_uploaded_inputs(
    state: MutableMapping[str, object],
    audit_metadata: MutableMapping[str, object],
    config: AppConfig,
) -> tuple[ExecutionResult, bytes | None, str | None]:
    if state["input_mode"] == INPUT_MODE_TWO:
        return web_pipeline.run_uploaded_tasks_many(
            first_file_bytes=bytes(state["first_uploaded_file_bytes"]),
            first_suffix=str(state["first_uploaded_file_suffix"]),
            first_logical_name=str(state["first_logical_name"]),
            first_uploaded_file_name=str(state["first_uploaded_file_name"]),
            second_file_bytes=bytes(state["second_uploaded_file_bytes"]),
            second_suffix=str(state["second_uploaded_file_suffix"]),
            second_logical_name=str(state["second_logical_name"]),
            second_uploaded_file_name=str(state["second_uploaded_file_name"]),
            task_text=str(state["task_text"]),
            audit_metadata=audit_metadata,
            config=config,
            cache_state=state,
        )
    return web_pipeline.run_uploaded_task(
        bytes(state["uploaded_file_bytes"]),
        str(state["uploaded_file_suffix"]),
        str(state["task_text"]),
        uploaded_file_name=str(state["uploaded_file_name"]),
        audit_metadata=audit_metadata,
        config=config,
        cache_state=state,
    )


def _run_generate(config: AppConfig) -> None:
    state = st.session_state
    audit_start = time.monotonic()
    audit_metadata: dict[str, object] = {"provider_called": False}
    error_category: ErrorCategory | None = "unknown_failure"
    try:
        result, output_bytes, output_file_name = _run_uploaded_inputs(
            state, audit_metadata, config
        )
        if not result.success:
            error_category = result.error_category or "sandbox_failure"
            mark_run_failure(state, format_execution_error(result))
        elif output_bytes is None or output_file_name is None:
            mark_run_failure(state, "Output file was not available.")
        else:
            preview = web_inputs.load_output_preview(output_bytes, Path(output_file_name).suffix)
            mark_run_success(state, preview, output_bytes, output_file_name)
            error_category = None
    except Exception as exc:
        error_category = exception_category(exc)
        mark_run_failure(state, format_exception_error(exc))
    finally:
        web_audit.write_streamlit_audit_event(
            state,
            audit_metadata,
            duration_ms=int((time.monotonic() - audit_start) * 1000),
            error_category=error_category,
            config=config,
        )
    if error_category is None:
        st.success("Generation succeeded.")


def _handle_generate_click(config: AppConfig) -> None:
    state = st.session_state
    can_run, validation_error = web_inputs.can_generate(state)
    if not can_run:
        mark_validation_error(state, validation_error or "Cannot generate.")
        return

    now = time.monotonic()
    last_run_timestamp = state["last_run_timestamp"]
    accepted, rate_limit_error = check_rate_limit(
        int(state["run_count"]),
        float(last_run_timestamp) if last_run_timestamp is not None else None,
        now,
    )
    if not accepted:
        mark_validation_error(state, rate_limit_error or "Cannot generate.")
        return
    begin_accepted_run(state, now=now)
    _run_generate(config)


def _render_generate_controls(
    config: AppConfig, current_input_error: str | None
) -> None:
    state = st.session_state
    remaining_runs = get_remaining_runs(int(state["run_count"]))
    st.caption(f"Remaining runs this session: {remaining_runs}")
    can_run, disabled_reason = web_inputs.can_generate(state)
    current_validation_error = current_input_error or disabled_reason
    if (
        not can_run
        and current_validation_error is not None
        and (
            state["input_mode"] == INPUT_MODE_TWO
            or current_input_error is not None
            or int(state["run_count"]) >= MAX_RUNS_PER_SESSION
        )
    ):
        if current_input_error is None:
            mark_validation_error(state, current_validation_error)
    elif can_run or state["input_mode"] != INPUT_MODE_TWO:
        web_inputs.clear_input_error_state(state)

    if st.button("Generate", disabled=not can_run):
        _handle_generate_click(config)


def _render_output() -> None:
    state = st.session_state
    st.subheader("Output")
    result_preview = state["result_preview"]
    if result_preview is not None:
        st.caption(f"Showing up to {web_inputs.PREVIEW_MAX_ROWS} preview rows.")
        st.dataframe(result_preview)
    else:
        st.info("Output preview will appear here after a successful run.")

    output_bytes = state["output_bytes"]
    output_file_name = state["output_file_name"]
    if output_bytes is not None and output_file_name is not None:
        st.download_button(
            label="Download output",
            data=output_bytes,
            file_name=str(output_file_name),
            mime=web_inputs.download_mime_type(Path(str(output_file_name)).suffix),
        )

    st.subheader("Errors")
    if state["error_message"]:
        st.error(str(state["error_message"]))
    else:
        st.info("No errors.")


def main() -> None:
    initialize_session_state()
    st.title("SnapScript")
    try:
        config = default_web_config()
    except InputValidationError as exc:
        st.error(f"Invalid SnapScript configuration. {format_error(exception_category(exc), exc)}")
        return
    st.write("Transform a CSV or Excel file with a natural-language task.")
    render_runtime_sidebar(config)

    current_input_error = _render_input_controls()
    web_assistant.render_prompt_coach(st.session_state, config)
    web_assistant.render_ai_rewrite_controls(st.session_state, config)
    _render_generate_controls(config, current_input_error)
    _render_output()


if __name__ == "__main__":
    main()
