"""Privacy-preserving audit records for the Streamlit interface."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import cast

from snapscript.config import AppConfig
from snapscript.core import audit_logger
from snapscript.core.models import ErrorCategory, MultiFileSchemaReport, SchemaReport
from snapscript.interfaces.web_state import INPUT_MODE_SINGLE

AUDIT_INTERFACE = "streamlit"
AUDIT_LOG_PATH = audit_logger.DEFAULT_AUDIT_LOG_PATH


def _schema_summary_for_audit(schema: SchemaReport) -> dict[str, object]:
    return {
        "filename": schema.filename,
        "file_type": schema.file_type,
        "row_count": schema.row_count,
        "file_size_bytes": schema.file_size_bytes,
        "encoding": schema.encoding,
        "sheet_names": schema.sheet_names,
        "columns": [
            {
                "name": column.name,
                "dtype": column.dtype,
                "null_count": column.null_count,
                "unique_count": column.unique_count,
            }
            for column in schema.columns
        ],
    }


def _multi_schema_summary_for_audit(
    multi_schema: MultiFileSchemaReport,
) -> dict[str, object]:
    return {
        "files": [
            {
                "name": file_schema.name,
                "schema": _schema_summary_for_audit(file_schema.schema),
            }
            for file_schema in multi_schema.files
        ]
    }


def schema_summary_for_audit(
    schema: SchemaReport | MultiFileSchemaReport,
) -> dict[str, object]:
    if isinstance(schema, MultiFileSchemaReport):
        return _multi_schema_summary_for_audit(schema)
    return _schema_summary_for_audit(schema)


def write_task_rewrite_audit_event(
    *,
    duration_ms: int,
    provider: str,
    model: str,
    provider_called: bool,
    success: bool,
    original_task: str,
    rewritten_task: str | None,
    schema_summary: object | None,
    error_category: ErrorCategory | None,
    api_call: dict[str, object] | None = None,
) -> None:
    event = audit_logger.build_audit_event(
        interface=AUDIT_INTERFACE, provider=provider, model=model,
        provider_called=provider_called, success=success, duration_ms=duration_ms,
        task_text=original_task, schema_summary=schema_summary,
        error_category=error_category, include_debug=False,
    )
    event = {key: value for key, value in event.items() if value is not None or key in {
        "error_category", "schema_summary_sha256",
    }}
    event.update({
        "event_type": "task_rewrite",
        "api_calls": [api_call] if api_call else [],
        "original_task_sha256": event.pop("task_text_sha256", None),
        "rewritten_task_sha256": (
            audit_logger.sha256_text(rewritten_task)
            if success and rewritten_task
            else None
        ),
    })
    audit_logger.write_audit_event_best_effort(event, log_path=AUDIT_LOG_PATH)


def write_streamlit_audit_event(
    state: MutableMapping[str, object],
    audit_metadata: MutableMapping[str, object],
    *,
    duration_ms: int,
    error_category: ErrorCategory | None,
    config: AppConfig,
) -> None:
    calls = audit_metadata.get("api_calls", [])
    single_file = state["input_mode"] == INPUT_MODE_SINGLE
    input_file_name = (
        str(state["uploaded_file_name"])
        if single_file
        else ", ".join(
            str(state[f"{slot}_uploaded_file_name"]) for slot in ("first", "second")
        )
    )
    event = audit_logger.build_audit_event(
        interface=AUDIT_INTERFACE,
        provider=calls[-1]["provider"] if calls else config.llm_provider,
        model=calls[-1]["model"] if calls else config.default_model,
        provider_called=bool(audit_metadata.get("provider_called", False)),
        success=error_category is None,
        duration_ms=duration_ms,
        input_file_name=input_file_name,
        input_file_bytes=bytes(state["uploaded_file_bytes"]) if single_file else None,
        task_text=str(state["task_text"]),
        schema_summary=audit_metadata.get("schema_summary"),
        prompt_text=cast(str | None, audit_metadata.get("prompt_text")),
        output_file_name=cast(str | None, state["output_file_name"]),
        output_file_bytes=cast(bytes | None, state["output_bytes"]),
        error_category=error_category,
        system_prompt=cast(str | None, audit_metadata.get("system_prompt")),
        user_prompt=cast(str | None, audit_metadata.get("user_prompt")),
    )
    event["api_calls"] = calls
    audit_logger.write_audit_event_best_effort(event, log_path=AUDIT_LOG_PATH)
