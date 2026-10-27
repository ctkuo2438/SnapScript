"""Action boundaries: rejected requests have no work/audit/bookkeeping effects."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from helpers.web_helpers import METRICS, audit_events, uploaded_state
from snapscript.core import audit_logger, task_advisor
from snapscript.core.models import MultiFileSchemaReport, SchemaReport
from snapscript.core.provider import ProviderCallError
from snapscript.interfaces import web, web_assistant


@pytest.mark.parametrize("two_files", [False, True])
def test_rewrite_handoff_preserves_task_advice_and_all_named_schemas(web_runtime, two_files):
    state = uploaded_state(two_files)
    if two_files:
        state["second_uploaded_file_bytes"] = b"sku,name\np1,Keyboard\n"

    web_assistant._handle_rewrite_click(state, web_runtime.config)

    web_runtime.rewrite.assert_called_once()
    call = web_runtime.rewrite.call_args
    task, schema = call.args
    assert task == state["task_text"]
    assert isinstance(schema, MultiFileSchemaReport if two_files else SchemaReport)
    reports = {item.name: item.schema for item in schema.files} if two_files else {"orders": schema}
    expected = {"orders": ["order_id", "amount"], **({"products": ["sku", "name"]} if two_files else {})}
    assert {name: [column.name for column in report.columns] for name, report in reports.items()} == expected
    assert call.kwargs.get("advice") == task_advisor.advise_task(state["task_text"], schema)
    assert call.kwargs["config"] is web_runtime.config


@pytest.mark.parametrize("two_files", [False, True])
@pytest.mark.parametrize("reason,expected", [
    ("missing", "Upload"), ("blank", "required"),
    ("limit", "limit reached"), ("cooldown", "wait"),
])
def test_blocked_generate_preserves_budget_and_writes_no_audit(monkeypatch, web_runtime, two_files, reason, expected):
    state = uploaded_state(two_files)
    state.update(run_count=3, last_run_timestamp=100.0, rewrite_count=2)
    if reason == "missing":
        state["first_uploaded_file_bytes" if two_files else "uploaded_file_bytes"] = None
    elif reason == "blank":
        state["task_text"] = " "
    elif reason == "limit":
        state["run_count"] = 10
    else:
        state["last_run_timestamp"] = 122.0
    before = state["run_count"], state["last_run_timestamp"], state["rewrite_count"]
    work = Mock()
    monkeypatch.setattr(web, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(web, "time", SimpleNamespace(monotonic=lambda: 123.0))
    monkeypatch.setattr(web, "_run_generate", work)

    web._handle_generate_click(web_runtime.config)

    work.assert_not_called()
    web_runtime.generate.assert_not_called()
    web_runtime.rewrite.assert_not_called()
    assert (state["run_count"], state["last_run_timestamp"], state["rewrite_count"]) == before
    assert expected.lower() in state["error_message"].lower()
    assert audit_events(web_runtime.audit_path) == []


@pytest.mark.parametrize("two_files", [False, True])
@pytest.mark.parametrize("reason", ["missing", "blank", "limit", "cooldown"])
def test_blocked_rewrite_preserves_both_budgets(monkeypatch, web_runtime, two_files, reason):
    state = uploaded_state(two_files)
    state.update(rewrite_count=2, last_rewrite_timestamp=100.0, run_count=10)
    if reason == "missing":
        state["first_uploaded_file_bytes" if two_files else "uploaded_file_bytes"] = None
    elif reason == "blank":
        state["task_text"] = " "
    elif reason == "limit":
        state["rewrite_count"] = 10
    else:
        state["last_rewrite_timestamp"] = 122.0
    before = state["rewrite_count"], state["last_rewrite_timestamp"], state["run_count"]
    monkeypatch.setattr(web_assistant, "time", SimpleNamespace(monotonic=lambda: 123.0))

    web_assistant._handle_rewrite_click(state, web_runtime.config)

    assert state["rewrite_error_message"]
    assert (state["rewrite_count"], state["last_rewrite_timestamp"], state["run_count"]) == before
    web_runtime.generate.assert_not_called()
    web_runtime.rewrite.assert_not_called()
    assert audit_events(web_runtime.audit_path) == []


@pytest.mark.parametrize("two_files", [False, True])
@pytest.mark.parametrize("outcome", ["success", "provider_failure", "audit_failure"])
def test_accepted_rewrite_consumes_budget_and_preserves_previous_output(monkeypatch, web_runtime, two_files, outcome):
    state = uploaded_state(two_files)
    preview = object()
    state.update(rewrite_count=2, run_count=10, last_rewrite_timestamp=100.0,
                 output_bytes=b"old output", output_file_name="old.csv", result_preview=preview)
    monkeypatch.setattr(web_assistant, "time", SimpleNamespace(monotonic=lambda: 123.0))
    if outcome == "provider_failure":
        error = ProviderCallError("token=fixture-secret")
        error.api_calls = [METRICS]
    elif outcome == "audit_failure":
        monkeypatch.setattr(audit_logger, "append_audit_event", Mock(side_effect=OSError("fixture disk failure")))
    observed_budgets = []

    def reply(*args, **kwargs):
        observed_budgets.append((state["rewrite_count"], state["last_rewrite_timestamp"]))
        if outcome == "provider_failure":
            raise error
        return web_runtime.rewrite.return_value

    web_runtime.rewrite.side_effect = reply

    web_assistant._handle_rewrite_click(state, web_runtime.config)

    web_runtime.rewrite.assert_called_once()
    web_runtime.generate.assert_not_called()
    assert observed_budgets == [(3, 123.0)]
    assert (state["rewrite_count"], state["last_rewrite_timestamp"], state["run_count"]) == (3, 123.0, 10)
    assert state["is_rewriting_task"] is False
    assert state["result_preview"] is preview
    assert (state["output_bytes"], state["output_file_name"]) == (b"old output", "old.csv")
    failed = outcome == "provider_failure"
    assert (state["rewritten_task"] is None) is failed
    assert bool(state["rewrite_error_message"]) is failed
    assert "fixture-secret" not in str(state["rewrite_error_message"])
    events = audit_events(web_runtime.audit_path)
    if outcome != "audit_failure":
        assert len(events) == 1
        assert events[0]["success"] is not failed
        assert events[0]["provider_called"] is True
        assert "fixture-secret" not in web_runtime.audit_path.read_text()
