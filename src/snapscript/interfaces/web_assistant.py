"""Prompt coaching and the optional provider-backed task rewrite UI."""
from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import asdict
import time
from types import ModuleType
import streamlit as st

from snapscript.config import AppConfig
from snapscript.core import schema_inspector, task_advisor
from snapscript.core.models import MultiFileSchemaReport, SchemaReport, TaskAdvice
from snapscript.interfaces.errors import ERROR_MAX_CHARS, exception_category, format_error
from snapscript.interfaces.web_inputs import (
    inspect_uploaded_schema, normalize_task_text, validate_task_text, validate_two_file_upload_state,
)
from snapscript.interfaces.web_audit import (
    schema_summary_for_audit, write_task_rewrite_audit_event,
)
from snapscript.interfaces.web_state import (
    INPUT_MODE_SINGLE, INPUT_MODE_TWO, MAX_REWRITES_PER_SESSION,
    begin_accepted_rewrite, check_rewrite_rate_limit, get_remaining_rewrites, update_input_state,
)

TASK_REWRITE_INPUT_ERROR_MESSAGE = "Could not improve the task. Check the uploaded files and task text."


def _task_rewriter_module() -> ModuleType:
    from snapscript.core import task_rewriter

    return task_rewriter


def build_prompt_coach_advice(
    state: MutableMapping[str, object],
    config: AppConfig,
) -> TaskAdvice | None:
    task_text = str(state.get("task_text", ""))
    if not normalize_task_text(task_text):
        return None

    try:
        schema = inspect_uploaded_schema(state, config)
    except (ValueError, OSError, schema_inspector.SchemaInspectionError):
        return None

    return task_advisor.advise_task(task_text, schema)


def can_improve_task(
    state: MutableMapping[str, object],
) -> tuple[bool, str | None]:
    try:
        validate_task_text(str(state.get("task_text", "")))
    except ValueError as exc:
        return False, str(exc)

    if str(state.get("input_mode", INPUT_MODE_SINGLE)) == INPUT_MODE_TWO:
        try:
            validate_two_file_upload_state(state)
        except ValueError as exc:
            return False, str(exc)
    elif (
        state.get("uploaded_file_bytes") is None
        or state.get("uploaded_file_suffix") is None
    ):
        return False, "Upload a CSV or Excel file before improving the task."

    return True, None


def build_task_rewrite_context(
    state: MutableMapping[str, object],
    config: AppConfig,
) -> tuple[SchemaReport | MultiFileSchemaReport, TaskAdvice]:
    task_text = validate_task_text(str(state.get("task_text", "")))
    schema = inspect_uploaded_schema(state, config)
    return schema, task_advisor.advise_task(task_text, schema)


def improve_task_with_ai(state: MutableMapping[str, object], config: AppConfig) -> None:
    start = time.monotonic()
    accepted = bool(state.get("is_rewriting_task", False))
    event = dict(
        provider=config.llm_provider, model=config.default_model, provider_called=False,
        success=False, original_task=str(state.get("task_text", "")), rewritten_task=None,
        schema_summary=None, error_category=None, api_call=None,
    )
    rewriter = _task_rewriter_module()
    try:
        task = validate_task_text(str(state.get("task_text", "")))
        schema, advice = build_task_rewrite_context(state, config)
        event["schema_summary"] = schema_summary_for_audit(schema)
        event["provider_called"] = True
        rewritten = rewriter.rewrite_task(task, schema, advice=advice, config=config)
        state["rewritten_task"], state["rewrite_error_message"] = rewritten.rewritten_task, None
        event.update(
            rewritten_task=rewritten.rewritten_task, provider=rewritten.provider,
            model=rewritten.model, success=True,
            api_call=asdict(rewritten.api_call) if rewritten.api_call else None,
        )
    except Exception as exc:
        state["rewritten_task"], state["rewrite_error_message"] = None, _format_task_rewrite_error(exc)
        event["error_category"] = exception_category(exc)
        calls = getattr(exc, "api_calls", [])
        if hasattr(exc, "api_calls"):
            event["provider_called"] = bool(calls)
        if calls:
            event.update(api_call=asdict(calls[-1]), provider=calls[-1].provider, model=calls[-1].model)
    finally:
        if accepted:
            write_task_rewrite_audit_event(duration_ms=int((time.monotonic() - start) * 1000), **event)
        state["is_rewriting_task"] = False


def _format_task_rewrite_error(exc: Exception) -> str:
    prefix = "Could not improve the task. "
    return prefix + format_error(exception_category(exc), exc, max_chars=ERROR_MAX_CHARS - len(prefix))


def render_prompt_coach(
    state: MutableMapping[str, object],
    config: AppConfig,
) -> None:
    advice = build_prompt_coach_advice(
        state,
        config=config,
    )
    if advice is None:
        return

    st.subheader("Prompt Coach")
    _render_prompt_coach_status(advice)
    if advice.missing_details:
        st.write("Missing details:")
        for detail in advice.missing_details:
            st.write(f"- {detail}")
    if advice.suggestions:
        st.write("Suggestions:")
        for suggestion in advice.suggestions:
            st.write(f"- {suggestion}")


def _handle_rewrite_click(state: MutableMapping[str, object], config: AppConfig) -> None:
    can_rewrite, validation_error = can_improve_task(state)
    if not can_rewrite:
        state["rewrite_error_message"] = validation_error or TASK_REWRITE_INPUT_ERROR_MESSAGE
        return
    now = time.monotonic()
    last_rewrite = state.get("last_rewrite_timestamp")
    accepted, error = check_rewrite_rate_limit(
        int(state.get("rewrite_count", 0)), float(last_rewrite) if last_rewrite is not None else None, now,
    )
    if not accepted:
        state["rewrite_error_message"] = error or "Cannot improve the task."
        return
    begin_accepted_rewrite(state, now)
    improve_task_with_ai(state, config)


def render_ai_rewrite_controls(
    state: MutableMapping[str, object],
    config: AppConfig,
) -> None:
    st.subheader("AI Task Rewrite")
    remaining_rewrites = get_remaining_rewrites(
        int(state.get("rewrite_count", 0))
    )
    st.caption(f"Remaining AI rewrites this session: {remaining_rewrites}")
    can_rewrite, _disabled_reason = can_improve_task(state)
    rewrite_limit_reached = (
        int(state.get("rewrite_count", 0)) >= MAX_REWRITES_PER_SESSION
    )
    if rewrite_limit_reached:
        state["rewrite_error_message"] = "Rewrite limit reached for this session."
    rewrite_disabled = (
        not can_rewrite
        or rewrite_limit_reached
        or bool(state.get("is_rewriting_task", False))
    )
    if st.button("Improve task with AI", disabled=rewrite_disabled):
        _handle_rewrite_click(state, config)

    rewrite_error = state.get("rewrite_error_message")
    if rewrite_error:
        st.error(str(rewrite_error))

    rewritten_task = state.get("rewritten_task")
    if rewritten_task:
        st.write("Rewritten task:")
        st.write(str(rewritten_task))
        if st.button("Use rewritten task"):
            update_input_state(state, task_text=str(rewritten_task))
            st.rerun()


def _render_prompt_coach_status(advice: TaskAdvice) -> None:
    status = advice.quality.replace("_", " ").title()
    message = f"Status: {status}"
    if advice.quality == "good":
        st.success(message)
    elif advice.quality == "too_vague":
        st.warning(message)
    else:
        st.info(message)
