"""Direct assertions over persisted web audit records, with synthetic data only."""
import hashlib
import json

import pytest

from helpers.web_helpers import INPUT_BYTES, METRICS, TASK, audit_events, uploaded_state
from snapscript.core.models import ColumnInfo, MultiFileSchemaReport, NamedSchemaReport, SchemaReport
from snapscript.interfaces import web_audit


@pytest.mark.parametrize("two_files", [False, True])
def test_generate_audit_contains_hashes_and_actual_call_metadata(web_runtime, two_files):
    state = uploaded_state(two_files)
    output = b"order_id,amount\n2,20\n"
    state.update(output_file_name="output.csv", output_bytes=output)
    metadata = {"provider_called": True, "schema_summary": {"rows": 2},
                "prompt_text": "private prompt", "system_prompt": "private system", "user_prompt": "private cells",
                "api_calls": [dict(provider=METRICS.provider, model=METRICS.model, input_tokens=10, output_tokens=5)]}

    web_audit.write_streamlit_audit_event(state, metadata, duration_ms=7, error_category=None, config=web_runtime.config)

    event, = audit_events(web_runtime.audit_path)
    assert event["success"] is True
    assert event["duration_ms"] == 7
    assert event["provider"] == METRICS.provider
    assert event["model"] == METRICS.model
    assert event["api_calls"] == metadata["api_calls"]
    assert event["task_text_sha256"] == hashlib.sha256(TASK.encode()).hexdigest()
    assert event["prompt_sha256"] == hashlib.sha256(b"private prompt").hexdigest()
    assert event["output_file_sha256"] == hashlib.sha256(output).hexdigest()
    assert event["output_file_name"] == "output.csv"
    assert event["input_file_name"] == ("first.csv, second.csv" if two_files else "orders.csv")
    assert event["input_file_sha256"] == (None if two_files else hashlib.sha256(INPUT_BYTES).hexdigest())
    assert event["input_file_size_bytes"] == (None if two_files else len(INPUT_BYTES))
    raw = web_runtime.audit_path.read_text()
    assert all(value not in raw for value in (TASK, "private prompt", "private system", "private cells", "order_id,amount"))


@pytest.mark.parametrize("success", [False, True])
def test_rewrite_audit_is_metadata_only_even_in_debug_mode(monkeypatch, web_runtime, success):
    monkeypatch.setenv("SNAPSCRIPT_AUDIT_INCLUDE_PROMPTS", "1")
    original, rewritten = "private original token=fixture", "private rewrite"

    web_audit.write_task_rewrite_audit_event(
        duration_ms=9, provider=METRICS.provider, model=METRICS.model,
        provider_called=True, success=success, original_task=original,
        rewritten_task=rewritten if success else None, schema_summary={"row_count": 2},
        error_category=None if success else "provider_failure", api_call={"input_tokens": 10},
    )

    event, = audit_events(web_runtime.audit_path)
    assert event["event_type"] == "task_rewrite"
    assert event["success"] is success
    assert event["error_category"] == (None if success else "provider_failure")
    assert event["original_task_sha256"] == hashlib.sha256(original.encode()).hexdigest()
    assert event["rewritten_task_sha256"] == (hashlib.sha256(rewritten.encode()).hexdigest() if success else None)
    assert event["schema_summary_sha256"]
    assert event["api_calls"] == [{"input_tokens": 10}]
    assert not {"original_task", "rewritten_task", "task_text", "system_prompt", "user_prompt"}.intersection(event)
    raw = web_runtime.audit_path.read_text()
    assert all(text not in raw for text in (original, rewritten, "system_prompt", "user_prompt", "prompt_sha256"))
    assert "private original" not in raw


@pytest.mark.parametrize("many", [False, True])
def test_schema_audit_summary_omits_sample_values_and_rows(many):
    schema = SchemaReport("orders.csv", "csv", 1, 20,
        columns=[ColumnInfo("amount", "int64", 0, 1, ["private-cell"])],
        sample_rows=[{"amount": "private-cell"}])
    report = MultiFileSchemaReport([NamedSchemaReport("orders", schema)]) if many else schema

    summary = web_audit.schema_summary_for_audit(report)

    value = summary["files"][0]["schema"] if many else summary
    assert value["row_count"] == 1
    assert value["columns"] == [{"name": "amount", "dtype": "int64", "null_count": 0, "unique_count": 1}]
    assert "private-cell" not in json.dumps(summary)
    assert "sample" not in json.dumps(summary)
