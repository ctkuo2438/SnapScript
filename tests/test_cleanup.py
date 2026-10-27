"""Behavior checks for the scoped review cleanup, without external services."""
from dataclasses import replace
from io import BytesIO
import json
from unittest.mock import Mock

from anthropic import APITimeoutError, AuthenticationError, RateLimitError
import httpx
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from helpers.provider_helpers import FakeAnthropic, Response
from snapscript.config import AppConfig
from snapscript.core import code_generator, provider, sandbox_executor, schema_inspector, task_rewriter
from snapscript.core.models import PromptPayload, ProviderCallMetrics, ProviderReply, RewrittenTask
from snapscript.interfaces import cli, errors, web, web_audit, web_inputs, web_state


COPY_CODE = """from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd
pd.read_csv(INPUT_PATH).to_csv(OUTPUT_PATH, index=False)
"""


def test_provider_uses_explicit_budget_closes_client_and_records_actual_response(monkeypatch):
    FakeAnthropic.instances = []
    FakeAnthropic.response = Response("print('ok')", model="actual-model")
    monkeypatch.setattr(provider, "Anthropic", FakeAnthropic)
    generated = code_generator.generate(
        PromptPayload("system", "user"),
        config=AppConfig(provider_timeout_seconds=2.5, provider_max_retries=0),
    )
    client = FakeAnthropic.instances[-1]
    assert client.options == {"timeout": 2.5, "max_retries": 0}
    assert client.closed
    assert generated.model == generated.api_call.model == "actual-model"
    assert (generated.api_call.input_tokens, generated.api_call.output_tokens) == (12, 8)
    assert generated.api_call.latency_ms >= 0
    with pytest.raises(provider.CodeGenerationError) as captured:
        provider.call(PromptPayload("system", "x" * 40000), "fixture", AppConfig())
    assert captured.value.category == "input_validation"
    assert captured.value.api_calls == []
    assert len(FakeAnthropic.instances) == 1


@pytest.mark.parametrize("kind,category", [
    ("timeout", "provider_timeout"), ("rate", "provider_rate_limit"),
    ("auth", "provider_authentication"),
])
def test_provider_errors_keep_safe_typed_category_and_close_client(monkeypatch, kind, category):
    request = httpx.Request("POST", "https://provider.invalid/messages")
    if kind == "timeout":
        failure = APITimeoutError(request=request)
    else:
        status = 429 if kind == "rate" else 401
        error_type = RateLimitError if kind == "rate" else AuthenticationError
        failure = error_type(
            "private provider message sk-ant-fixture", body={"secret": "private"},
            response=httpx.Response(status, request=request),
        )
    FakeAnthropic.response = failure
    monkeypatch.setattr(provider, "Anthropic", FakeAnthropic)
    with pytest.raises(provider.ProviderCallError) as captured:
        provider.call(PromptPayload("private system", "private user"), "requested-model", AppConfig())
    error = captured.value
    assert error.category == category
    assert error.__cause__ is None
    assert str(error) == "Provider call failed"
    assert error.api_calls[0].model == "requested-model"
    assert error.api_calls[0].input_tokens is None
    assert FakeAnthropic.instances[-1].closed


@pytest.mark.parametrize("field,value", [
    ("max_retries", -1), ("provider_max_retries", -1), ("schema_sample_rows", -1),
    ("execution_timeout_seconds", 0), ("max_tokens", 1.5),
    ("max_output_file_size_bytes", 0), ("max_input_file_size_bytes", -1),
    ("max_capture_bytes", 0), ("schema_inspect_rows", 0), ("max_column_name_chars", 0),
    ("max_prompt_tokens", 0), ("provider_timeout_seconds", float("inf")),
    ("provider_timeout_seconds", float("nan")), ("temperature", 2),
])
def test_config_rejects_unusable_limits(field, value):
    with pytest.raises(ValueError, match=field):
        AppConfig(**{field: value})


def test_schema_cache_ignores_task_edits_and_invalidates_for_files_names_and_config(monkeypatch):
    inspect_many = Mock(wraps=schema_inspector.inspect_many)
    monkeypatch.setattr(schema_inspector, "inspect_many", inspect_many)
    state = {
        "input_mode": web_state.INPUT_MODE_TWO, "task_text": "merge",
        "first_logical_name": "orders", "first_uploaded_file_bytes": b"pid,amount\n1,10\n",
        "first_uploaded_file_suffix": ".csv", "first_uploaded_file_name": "orders.csv",
        "second_logical_name": "products", "second_uploaded_file_bytes": b"pid,name\n1,A\n",
        "second_uploaded_file_suffix": ".csv", "second_uploaded_file_name": "products.csv",
    }
    config = AppConfig()
    original = web_inputs.inspect_uploaded_schema(state, config)
    web_state.update_input_state(state, task_text="merge and sort")
    assert web_inputs.inspect_uploaded_schema(state, config) is original
    assert inspect_many.call_count == 1
    web_inputs.store_named_uploaded_file(state, "first", "orders.csv", b"pid,amount\n2,20\n")
    changed = web_inputs.inspect_uploaded_schema(state, config)
    assert changed.files[0].schema.sample_rows[0]["amount"] == 20
    web_state.update_input_state(state, first_logical_name="sales")
    renamed = web_inputs.inspect_uploaded_schema(state, config)
    assert renamed.files[0].name == "sales"
    web_inputs.inspect_uploaded_schema(state, replace(config, schema_sample_rows=0))
    assert inspect_many.call_count == 4


def test_real_app_reuses_schema_and_applies_rewritten_task(monkeypatch, tmp_path):
    monkeypatch.setenv("SNAPSCRIPT_SANDBOX_BACKEND", "subprocess")
    inspect = Mock(wraps=schema_inspector.inspect)
    monkeypatch.setattr(schema_inspector, "inspect", inspect)
    monkeypatch.setattr(web, "AppConfig", lambda: AppConfig(sandbox_backend="subprocess"))
    monkeypatch.setattr(web_audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    metrics = ProviderCallMetrics("anthropic", "fixture", 10, 5, 2)
    monkeypatch.setattr(provider, "call", lambda *args: ProviderReply(COPY_CODE, metrics))
    rewritten_text = "Keep rows where amount is greater than 1."
    rewrite = Mock(return_value=RewrittenTask("Copy rows.", rewritten_text, "anthropic", "fixture", metrics))
    monkeypatch.setattr(task_rewriter, "rewrite_task", rewrite)
    app = AppTest.from_file("app.py", default_timeout=10).run()
    app.file_uploader[0].set_value(("orders.csv", b"amount\n1\n2\n", "text/csv"))
    app.text_area[0].set_value("Copy rows.").run()
    assert not app.exception
    app.text_area[0].set_value("Copy all rows.").run()
    assert inspect.call_count == 1
    next(b for b in app.button if b.label == "Generate").click().run()
    assert not app.exception
    assert app.session_state["output_bytes"] is not None
    next(b for b in app.button if b.label == "Improve task with AI").click().run()
    assert not app.exception
    next(b for b in app.button if b.label == "Use rewritten task").click().run()
    assert not app.exception
    assert app.text_area[0].value == rewritten_text
    assert app.session_state["output_bytes"] is None
    assert len(app.get("download_button")) == 0
    assert inspect.call_count == 1
    assert app.session_state["run_count"] == app.session_state["rewrite_count"] == 1
    rewrite.assert_called_once()


def test_real_app_audit_keeps_all_attempts_and_actual_fallback_model(monkeypatch, tmp_path):
    monkeypatch.setenv("SNAPSCRIPT_SANDBOX_BACKEND", "subprocess")
    config = AppConfig(sandbox_backend="subprocess", max_retries=1)
    monkeypatch.setattr(web, "AppConfig", lambda: config)
    log = tmp_path / "audit.jsonl"
    monkeypatch.setattr(web_audit, "AUDIT_LOG_PATH", log)
    requests = []

    def call(prompt, model, config):
        requests.append(model)
        code = "raise ValueError('retry fixture')" if len(requests) == 1 else COPY_CODE
        return ProviderReply(code, ProviderCallMetrics("anthropic", model, 10, 5, 2))

    monkeypatch.setattr(provider, "call", call)
    app = AppTest.from_file("app.py", default_timeout=10).run()
    app.file_uploader[0].set_value(("orders.csv", b"amount\n1\n2\n", "text/csv"))
    app.text_area[0].set_value("Copy rows.").run()
    next(b for b in app.button if b.label == "Generate").click().run()
    assert not app.exception
    assert requests == [config.default_model, config.fallback_model]
    pd.testing.assert_frame_equal(pd.read_csv(BytesIO(app.session_state["output_bytes"])), pd.DataFrame({"amount": [1, 2]}))
    event = json.loads(log.read_text())
    assert event["success"] is True
    assert event["model"] == config.fallback_model
    assert [call["model"] for call in event["api_calls"]] == requests
    assert sum(call["input_tokens"] for call in event["api_calls"]) == 20
    assert "retry fixture" not in log.read_text()
    assert "system_prompt" not in event


def test_valid_long_filename_is_copied_under_a_short_internal_name(tmp_path):
    source, output = tmp_path / ("a" * 247 + ".csv"), tmp_path / "result.csv"
    source.write_text("amount\n1\n")
    original = source.read_bytes()
    result = sandbox_executor.execute(COPY_CODE, source, output, config=AppConfig())
    assert result.success, result.stderr
    assert source.read_bytes() == output.read_bytes() == original


def test_safety_named_column_does_not_classify_a_runtime_error_as_safety():
    from snapscript.core.models import ExecutionResult
    result = ExecutionResult(False, stderr="KeyError: 'safety_stock'", exit_code=1)
    assert errors.format_execution_error(result).startswith("Execution failed in the sandbox.")


def test_wide_csv_stops_before_provider_when_schema_exceeds_budget(monkeypatch, tmp_path, capsys):
    source = tmp_path / "wide.csv"
    columns = [f"column_{index}_" + "x" * 80 for index in range(400)]
    pd.DataFrame([[1] * len(columns)], columns=columns).to_csv(source, index=False)
    generate = Mock(side_effect=RuntimeError("Provider must not be called"))
    monkeypatch.setattr(code_generator, "generate", generate)
    assert cli.main(["Copy rows.", "--file", str(source), "--output", str(tmp_path / "out.csv"), "--yes"]) == 1
    assert generate.call_count == 0
    assert "Prompt is too large" in capsys.readouterr().err
