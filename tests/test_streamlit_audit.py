import json
from pathlib import Path

import pytest

from snapscript.core.models import (
    ExecutionResult,
    TaskAdvice,
)
from snapscript.interfaces import web
from helpers.streamlit_helpers import (
    FakeRewriteError,
    FakeStreamlit,
    FakeUploadedFile,
    _fake_rewriter_module,
    _schema,
    isolate_audit_log,
)


@pytest.mark.parametrize("success", [True, False])
def test_upload_pipeline_output_and_audit_metadata(monkeypatch, success) -> None:
    upload_bytes = b"order_id,amount,note\n1,1500,private-cell\n"
    output_bytes = b"order_id,amount\n1,1500\n"
    metadata: dict[str, object] = {}
    workspaces: list[Path] = []

    def fake_run(prompt, input_path, output_path, config=None):
        assert input_path.name == "input.csv"
        assert input_path.read_bytes() == upload_bytes
        assert output_path.name == "output.csv"
        assert output_path.parent == input_path.parent
        assert str(input_path.parent) not in prompt.user_prompt
        assert "Keep large orders." in prompt.user_prompt
        assert metadata["provider_called"] is True
        assert metadata["system_prompt"] == prompt.system_prompt
        assert metadata["user_prompt"] == prompt.user_prompt
        assert metadata["prompt_text"] == (
            f"{prompt.system_prompt}\n\n{prompt.user_prompt}"
        )
        workspaces.append(input_path.parent)
        output_path.write_bytes(output_bytes)
        return ExecutionResult(success=success)

    monkeypatch.setattr(web.retry_handler, "run", fake_run)

    result, returned_output, filename = web.run_uploaded_task(
        upload_bytes,
        ".csv",
        " Keep large orders. ",
        uploaded_file_name="orders.csv",
        audit_metadata=metadata,
    )

    assert result.success is success
    assert returned_output == (output_bytes if success else None)
    assert filename == ("orders_snapscript_output.csv" if success else None)
    summary = metadata["schema_summary"]
    assert isinstance(summary, dict)
    assert summary["row_count"] == 1
    assert len(summary["columns"]) == 3
    assert "sample_rows" not in summary
    assert "private-cell" not in json.dumps(summary)
    assert len(workspaces) == 1
    assert not workspaces[0].exists()


def test_accepted_successful_rewrite_writes_metadata_only_audit_event(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile(
        "orders.csv",
        b"order_id,amount\n1,10\n2,20\n",
    )
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="clean this with token=abc123",
        clicked_buttons={"Improve task with AI"},
    )
    events: list[dict[str, object]] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 300.0)
    monkeypatch.setattr(web, "build_prompt_coach_advice", lambda _state, config=None: None)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path, config=None: _schema())
    monkeypatch.setattr(
        web.task_advisor,
        "advise_task",
        lambda _task_text, _schema: TaskAdvice(
            quality="too_vague",
            missing_details=["desired operation"],
            suggestions=[],
        ),
    )
    monkeypatch.setattr(
        web,
        "_task_rewriter_module",
        lambda: _fake_rewriter_module(
            rewritten_task="Filter rows where amount is greater than 1000."
        ),
    )
    monkeypatch.setattr(
        web.audit_logger,
        "write_audit_event_best_effort",
        lambda event, log_path=web.AUDIT_LOG_PATH: events.append(event) or True,
    )

    web.main()

    assert len(events) == 1
    event = events[0]
    serialized = json.dumps(event, sort_keys=True)
    assert event["event_type"] == "task_rewrite"
    assert event["interface"] == "streamlit"
    assert event["provider"] == "test-provider"
    assert event["model"] == "test-model"
    assert event["success"] is True
    assert event["provider_called"] is True
    assert event["error_category"] is None
    assert event["original_task_sha256"] == web.audit_logger.sha256_text(
        "clean this with token=abc123"
    )
    assert event["rewritten_task_sha256"] == web.audit_logger.sha256_text(
        "Filter rows where amount is greater than 1000."
    )
    assert event["schema_summary_sha256"] is not None
    assert "clean this" not in serialized
    assert "Filter rows where amount" not in serialized
    assert "order_id,amount" not in serialized
    assert "prompt" not in serialized.lower()
    assert "generated_code" not in serialized
    assert "abc123" not in serialized

def test_accepted_failed_rewrite_writes_metadata_only_audit_event(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="clean this",
        clicked_buttons={"Improve task with AI"},
    )
    events: list[dict[str, object]] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 400.0)
    monkeypatch.setattr(web, "build_prompt_coach_advice", lambda _state, config=None: None)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path, config=None: _schema())
    monkeypatch.setattr(
        web.task_advisor,
        "advise_task",
        lambda _task_text, _schema: TaskAdvice(
            quality="too_vague",
            missing_details=[],
            suggestions=[],
        ),
    )
    monkeypatch.setattr(
        web,
        "_task_rewriter_module",
        lambda: _fake_rewriter_module(
            error=FakeRewriteError(
                "Traceback: ANTHROPIC_API_KEY=sk-ant-api03-secret"
            )
        ),
    )
    monkeypatch.setattr(
        web.audit_logger,
        "write_audit_event_best_effort",
        lambda event, log_path=web.AUDIT_LOG_PATH: events.append(event) or True,
    )

    web.main()

    assert len(events) == 1
    event = events[0]
    serialized = json.dumps(event, sort_keys=True)
    assert event["event_type"] == "task_rewrite"
    assert event["success"] is False
    assert event["provider_called"] is True
    assert event["rewritten_task_sha256"] is None
    assert event["error_category"] == "provider_failure"
    assert "clean this" not in serialized
    assert "Traceback" not in serialized
    assert "sk-ant" not in serialized

def test_blocked_rewrite_writes_no_audit_event(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="clean this",
        clicked_buttons={"Improve task with AI"},
    )
    fake_st.session_state["rewrite_count"] = 1
    fake_st.session_state["last_rewrite_timestamp"] = 100.0
    events: list[dict[str, object]] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 101.0)
    monkeypatch.setattr(
        web.audit_logger,
        "write_audit_event_best_effort",
        lambda event, log_path=web.AUDIT_LOG_PATH: events.append(event) or True,
    )

    web.main()

    assert events == []

def test_rewrite_audit_failure_does_not_break_rewrite_ux(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="clean this",
        clicked_buttons={"Improve task with AI"},
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 500.0)
    monkeypatch.setattr(web, "build_prompt_coach_advice", lambda _state, config=None: None)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path, config=None: _schema())
    monkeypatch.setattr(
        web.task_advisor,
        "advise_task",
        lambda _task_text, _schema: TaskAdvice(
            quality="too_vague",
            missing_details=[],
            suggestions=[],
        ),
    )
    monkeypatch.setattr(web, "_task_rewriter_module", _fake_rewriter_module)
    monkeypatch.setattr(
        web.audit_logger,
        "write_audit_event_best_effort",
        lambda _event, log_path=web.AUDIT_LOG_PATH: False,
    )

    web.main()

    assert fake_st.session_state["rewritten_task"] == (
        "Filter rows where amount is greater than 1000."
    )
    assert fake_st.session_state["rewrite_error_message"] is None

def test_main_accepted_successful_generate_writes_one_audit_event(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    events: list[dict[str, object]] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 50.0)
    monkeypatch.setattr(
        web.audit_logger,
        "write_audit_event_best_effort",
        lambda event, log_path=web.AUDIT_LOG_PATH: events.append(event) or True,
    )

    def fake_run_uploaded_task(
        _file_bytes: bytes,
        _suffix: str,
        _task_text: str,
        uploaded_file_name: str | None = None,
        audit_metadata: dict[str, object] | None = None,
        config: object | None = None,
    ) -> tuple[web.ExecutionResult, bytes, str]:
        if audit_metadata is not None:
            audit_metadata.update(
                {
                    "provider_called": True,
                    "schema_summary": {"columns": ["total"]},
                    "prompt_text": "system\n\nuser",
                }
            )
        return (
            web.ExecutionResult(success=True),
            b"order_id,total\n1,10\n",
            web.derive_output_file_name(uploaded_file_name, ".csv"),
        )

    monkeypatch.setattr(web, "run_uploaded_task", fake_run_uploaded_task)

    web.main()

    assert len(events) == 1
    event = events[0]
    assert event["interface"] == "streamlit"
    assert event["provider"] == "anthropic"
    assert event["model"] == web.AppConfig().default_model
    assert event["provider_called"] is True
    assert event["success"] is True
    assert event["duration_ms"] == 0
    assert isinstance(event["run_id"], str)
    assert event["input_file_name"] == "orders.csv"
    assert event["input_file_size_bytes"] == len(uploaded.getvalue())
    assert event["input_file_sha256"] == web.audit_logger.sha256_bytes(
        uploaded.getvalue()
    )
    assert event["task_text_sha256"] == web.audit_logger.sha256_text(
        "Keep rows."
    )
    assert event["schema_summary_sha256"] is not None
    assert event["prompt_sha256"] == web.audit_logger.sha256_text(
        "system\n\nuser"
    )
    assert "generated_code_sha256" not in event
    assert "generated_code" not in event
    assert "attempt_count" not in event
    assert event["output_file_name"] == "orders_snapscript_output.csv"
    assert event["output_file_sha256"] == web.audit_logger.sha256_bytes(
        b"order_id,total\n1,10\n"
    )
    assert "Keep rows." not in json.dumps(event)
    assert "order_id,total" not in json.dumps(event)


@pytest.mark.parametrize("input_mode", ["Single file", "Two files"])
@pytest.mark.parametrize(
    ("outcome", "error_category"),
    [
        ("success", None),
        ("execution_failure", "sandbox_failure"),
        ("provider_exception", "provider_failure"),
        ("missing_output", "unknown_failure"),
        ("invalid_preview", "unknown_failure"),
    ],
)
def test_generate_records_one_event_and_exposes_only_successful_outputs(
    monkeypatch: pytest.MonkeyPatch,
    input_mode: str,
    outcome: str,
    error_category: str | None,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        input_mode=input_mode,
        first_uploaded_file=uploaded,
        second_uploaded_file=FakeUploadedFile("products.csv", b"order_id,name\n1,A\n"),
        first_logical_name="orders",
        second_logical_name="products",
        task_text="Keep rows.",
    )
    fake_st.session_state.update(
        output_bytes=b"old output", output_file_name="old.csv", result_preview="old"
    )
    events: list[dict[str, object]] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web, "build_prompt_coach_advice", lambda _state, config=None: None)
    monkeypatch.setattr(
        web.audit_logger,
        "write_audit_event_best_effort",
        lambda event, log_path=web.AUDIT_LOG_PATH: events.append(event) or True,
    )

    def run_upload(
        *_args: object,
        audit_metadata: dict[str, object] | None = None,
        **_kwargs: object,
    ) -> tuple[ExecutionResult, bytes | None, str | None]:
        assert audit_metadata is not None
        audit_metadata["provider_called"] = True
        if outcome == "provider_exception":
            raise RuntimeError("ProviderCallError: token: fixture-demo-value")
        if outcome == "execution_failure":
            return (
                ExecutionResult(success=False, stderr="transform failed", exit_code=1),
                None,
                None,
            )
        if outcome == "missing_output":
            return ExecutionResult(success=True), None, None
        output = b"" if outcome == "invalid_preview" else uploaded.getvalue()
        return ExecutionResult(success=True), output, "output.csv"

    monkeypatch.setattr(web, "run_uploaded_task", run_upload)
    monkeypatch.setattr(web, "run_uploaded_tasks_many", run_upload)

    web.main()

    assert len(events) == 1
    assert events[0]["success"] is (error_category is None)
    assert events[0]["error_category"] == error_category
    assert events[0]["provider_called"] is True
    assert "fixture-demo-value" not in json.dumps(events[0])
    assert fake_st.session_state["run_count"] == 1
    assert fake_st.session_state["is_running"] is False
    downloads = [
        args for name, args, _kwargs in fake_st.calls if name == "download_button"
    ]
    if error_category is None:
        assert len(downloads) == 1
        assert fake_st.session_state["output_bytes"] == uploaded.getvalue()
    else:
        assert downloads == []
        assert fake_st.session_state["result_preview"] is None
        assert fake_st.session_state["output_bytes"] is None
        assert "fixture-demo-value" not in str(fake_st.session_state["error_message"])
        assert events[0]["output_file_sha256"] is None
    if input_mode == "Two files":
        assert events[0]["input_file_name"] == "orders.csv, products.csv"
        assert events[0]["input_file_sha256"] is None
        assert events[0]["input_file_size_bytes"] is None



def test_main_validation_blocked_generate_writes_no_audit_event(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(
        button_clicked=True,
        task_text="Keep rows.",
    )
    events: list[dict[str, object]] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web.audit_logger,
        "write_audit_event_best_effort",
        lambda event, log_path=web.AUDIT_LOG_PATH: events.append(event) or True,
    )

    web.main()

    assert events == []

def test_main_cooldown_blocked_generate_writes_no_audit_event(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    fake_st.session_state["run_count"] = 1
    fake_st.session_state["last_run_timestamp"] = 100.0
    events: list[dict[str, object]] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 102.0)
    monkeypatch.setattr(
        web.audit_logger,
        "write_audit_event_best_effort",
        lambda event, log_path=web.AUDIT_LOG_PATH: events.append(event) or True,
    )

    web.main()

    assert events == []

def test_main_run_limit_blocked_generate_writes_no_audit_event(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    fake_st.session_state["run_count"] = web.MAX_RUNS_PER_SESSION
    events: list[dict[str, object]] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web.audit_logger,
        "write_audit_event_best_effort",
        lambda event, log_path=web.AUDIT_LOG_PATH: events.append(event) or True,
    )

    web.main()

    assert events == []

def test_audit_logging_failure_does_not_break_successful_generate(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web.audit_logger,
        "append_audit_event",
        lambda _event, log_path=web.AUDIT_LOG_PATH: (_ for _ in ()).throw(
            OSError("cannot write audit log")
        ),
    )
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda _file_bytes, _suffix, _task_text, uploaded_file_name=None, audit_metadata=None, config=None: (
            web.ExecutionResult(success=True),
            b"order_id,total\n1,10\n",
            web.derive_output_file_name(uploaded_file_name, ".csv"),
        ),
    )

    web.main()

    assert fake_st.session_state["error_message"] is None
    assert fake_st.session_state["output_bytes"] == b"order_id,total\n1,10\n"
