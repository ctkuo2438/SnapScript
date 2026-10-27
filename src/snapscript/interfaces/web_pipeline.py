"""Prepare uploaded inputs once, then call the shared core pipeline."""
from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import asdict
from pathlib import Path
import tempfile

from snapscript.config import AppConfig
from snapscript.core import prompt_builder, retry_handler
from snapscript.core.models import ExecutionResult, MultiFileSchemaReport
from snapscript.interfaces.web_audit import schema_summary_for_audit
from snapscript.interfaces.web_inputs import (
    derive_multi_output_file_name, derive_output_file_name, inspect_uploaded_schema,
    materialize_uploads, validate_task_text, validate_upload_suffix,
)
from snapscript.interfaces.web_state import INPUT_MODE_SINGLE, INPUT_MODE_TWO


def run_uploaded_task(
    uploaded_file_bytes: bytes, upload_suffix: str, task_text: str,
    uploaded_file_name: str | None = None,
    audit_metadata: MutableMapping[str, object] | None = None, config: AppConfig | None = None,
    cache_state: MutableMapping[str, object] | None = None,
) -> tuple[ExecutionResult, bytes | None, str | None]:
    state = cache_state if cache_state is not None else {
        "input_mode": INPUT_MODE_SINGLE, "uploaded_file_bytes": uploaded_file_bytes,
        "uploaded_file_suffix": upload_suffix, "uploaded_file_name": uploaded_file_name,
        "task_text": task_text,
    }
    return _run_upload_state(state, audit_metadata, config)


def run_uploaded_tasks_many(
    *, first_file_bytes: bytes, first_suffix: str, first_logical_name: str,
    first_uploaded_file_name: str | None, second_file_bytes: bytes, second_suffix: str,
    second_logical_name: str, second_uploaded_file_name: str | None, task_text: str,
    audit_metadata: MutableMapping[str, object] | None = None, config: AppConfig | None = None,
    cache_state: MutableMapping[str, object] | None = None,
) -> tuple[ExecutionResult, bytes | None, str | None]:
    state = cache_state if cache_state is not None else {
        "input_mode": INPUT_MODE_TWO, "task_text": task_text,
        "first_uploaded_file_bytes": first_file_bytes, "first_uploaded_file_suffix": first_suffix,
        "first_uploaded_file_name": first_uploaded_file_name, "first_logical_name": first_logical_name,
        "second_uploaded_file_bytes": second_file_bytes, "second_uploaded_file_suffix": second_suffix,
        "second_uploaded_file_name": second_uploaded_file_name, "second_logical_name": second_logical_name,
    }
    return _run_upload_state(state, audit_metadata, config)


def _run_upload_state(
    state: MutableMapping[str, object], audit: MutableMapping[str, object] | None, config: AppConfig | None,
) -> tuple[ExecutionResult, bytes | None, str | None]:
    config = config if config is not None else AppConfig()
    task = validate_task_text(str(state["task_text"]))
    single = state["input_mode"] == INPUT_MODE_SINGLE
    suffix = validate_upload_suffix(f"output{state['uploaded_file_suffix']}") if single else ".csv"
    with tempfile.TemporaryDirectory(prefix="snapscript_web_") as name:
        directory = Path(name).resolve()
        inputs = materialize_uploads(state, directory)
        schema = inspect_uploaded_schema(state, config, inputs)
        output = directory / f"output{suffix}"
        build = prompt_builder.build_many if isinstance(schema, MultiFileSchemaReport) else prompt_builder.build
        prompt = build(task, schema, config=config)
        if audit is not None:
            audit.update({
                "schema_summary": schema_summary_for_audit(schema),
                "prompt_text": f"{prompt.system_prompt}\n\n{prompt.user_prompt}", "system_prompt": prompt.system_prompt,
                "user_prompt": prompt.user_prompt, "provider_called": True,
            })
        run = retry_handler.run if single else retry_handler.run_many
        try:
            result = run(prompt, inputs[0].path if single else inputs, output, config=config)
        except Exception as exc:
            if audit is not None:
                audit["api_calls"] = [asdict(call) for call in getattr(exc, "api_calls", [])]
                if hasattr(exc, "api_calls"):
                    audit["provider_called"] = bool(exc.api_calls)
            raise
        if audit is not None:
            audit["api_calls"] = [asdict(call) for call in result.api_calls]
            if result.error_category in {"backend_unavailable", "input_validation"} and not result.api_calls:
                audit["provider_called"] = False
        if not result.success:
            return result, None, None
        filename = (
            derive_output_file_name(state.get("uploaded_file_name"), suffix) if single
            else derive_multi_output_file_name()
        )
        return result, output.read_bytes(), filename
