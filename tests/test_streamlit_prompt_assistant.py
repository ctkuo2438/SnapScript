from pathlib import Path

import pandas as pd
import pytest

from snapscript.core.models import (
    ExecutionResult,
    MultiFileSchemaReport,
    SchemaReport,
    TaskAdvice,
)
from snapscript.interfaces import web
from helpers.streamlit_helpers import (
    FakeRewriteError,
    FakeStreamlit,
    FakeUploadedFile,
    _button_disabled,
    _button_disabled_by_label,
    _fake_rewriter_module,
    _multi_schema,
    _rendered_text,
    _schema,
)


@pytest.fixture(autouse=True)
def isolate_audit_log(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(web, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")


def test_prompt_coach_renders_for_single_file_after_task_and_schema(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="Filter rows where amount is greater than 1000",
    )
    seen: dict[str, object] = {}
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path: _schema())
    monkeypatch.setattr(
        web.task_advisor,
        "advise_task",
        lambda task_text, schema: (
            seen.update({"task_text": task_text, "schema": schema})
            or TaskAdvice(
                quality="good",
                missing_details=[],
                suggestions=["Task looks clear."],
            )
        ),
    )

    web.main()

    rendered = _rendered_text(fake_st.calls)
    assert "Prompt Coach" in rendered
    assert "Status: Good" in rendered
    assert "Task looks clear." in rendered
    assert seen["task_text"] == "Filter rows where amount is greater than 1000"
    assert isinstance(seen["schema"], SchemaReport)

def test_prompt_coach_renders_for_two_file_mode_after_task_and_schema(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(
        input_mode="Two files",
        first_uploaded_file=FakeUploadedFile("orders.csv", b"order_id,pid\n1,p1\n"),
        second_uploaded_file=FakeUploadedFile("products.csv", b"pid,name\np1,x\n"),
        first_logical_name="orders",
        second_logical_name="products",
        task_text="merge these files",
    )
    seen: dict[str, object] = {}
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web.schema_inspector,
        "inspect_many",
        lambda specs: (
            seen.update({"specs": specs})
            or _multi_schema()
        ),
    )
    monkeypatch.setattr(
        web.task_advisor,
        "advise_task",
        lambda task_text, schema: (
            seen.update({"task_text": task_text, "schema": schema})
            or TaskAdvice(
                quality="needs_detail",
                missing_details=["join key", "join type"],
                suggestions=["Name the shared column and join type."],
                suggested_task=(
                    "Merge orders and products using pid with a left join."
                ),
            )
        ),
    )

    web.main()

    rendered = _rendered_text(fake_st.calls)
    assert "Prompt Coach" in rendered
    assert "Status: Needs Detail" in rendered
    assert "join key" in rendered
    assert "join type" in rendered
    assert "Name the shared column and join type." in rendered
    assert "Guidance:" not in rendered
    assert "Merge orders and products using pid with a left join." not in rendered
    assert _button_disabled(fake_st.calls) is False
    assert [spec.name for spec in seen["specs"]] == ["orders", "products"]
    assert isinstance(seen["schema"], MultiFileSchemaReport)

def test_prompt_coach_too_vague_advice_does_not_disable_generate(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="clean this",
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path: _schema())
    monkeypatch.setattr(
        web.task_advisor,
        "advise_task",
        lambda _task_text, _schema: TaskAdvice(
            quality="too_vague",
            missing_details=["desired operation"],
            suggestions=["Describe what should change."],
        ),
    )

    web.main()

    assert _button_disabled(fake_st.calls) is False
    rendered = _rendered_text(fake_st.calls)
    assert "Status: Too Vague" in rendered
    assert "desired operation" in rendered

def test_prompt_coach_rendering_does_not_call_execution_pipeline(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="Filter rows where amount is greater than 1000",
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path: _schema())
    monkeypatch.setattr(
        web.task_advisor,
        "advise_task",
        lambda _task_text, _schema: TaskAdvice(
            quality="good",
            missing_details=[],
            suggestions=[],
        ),
    )
    monkeypatch.setattr(
        web.prompt_builder,
        "build",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("prompt_builder.build must not be called")
        ),
    )
    monkeypatch.setattr(
        web.retry_handler,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("retry_handler.run must not be called")
        ),
    )

    web.main()

    assert fake_st.session_state["result_preview"] is None
    assert fake_st.session_state["output_bytes"] is None
    assert fake_st.session_state["output_file_name"] is None
    assert not any(name == "download_button" for name, _args, _kwargs in fake_st.calls)

def test_prompt_coach_rendering_does_not_load_task_rewriter(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="Filter rows where amount is greater than 1000",
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path: _schema())
    monkeypatch.setattr(
        web.task_advisor,
        "advise_task",
        lambda _task_text, _schema: TaskAdvice(
            quality="good",
            missing_details=[],
            suggestions=[],
        ),
    )
    monkeypatch.setattr(
        web,
        "_task_rewriter_module",
        lambda: (_ for _ in ()).throw(
            AssertionError("Prompt Coach must not load task_rewriter")
        ),
    )

    web.main()

    assert fake_st.session_state["rewritten_task"] is None

def test_prompt_coach_does_not_render_guidance_or_suggested_task(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    previous_preview = pd.DataFrame({"old": [1]})
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="clean this",
        clicked_buttons={"Use suggested task"},
    )
    fake_st.session_state.update(
        {
            "result_preview": previous_preview,
            "output_bytes": b"old",
            "output_file_name": "old.csv",
            "run_count": 3,
        }
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path: _schema())
    monkeypatch.setattr(
        web.task_advisor,
        "advise_task",
        lambda _task_text, _schema: TaskAdvice(
            quality="needs_detail",
            missing_details=["target column"],
            suggestions=["Mention the column to use."],
            suggested_task="Filter rows where amount is greater than 1000.",
        ),
    )

    web.main()

    labels = [
        str(args[0])
        for name, args, _kwargs in fake_st.calls
        if name == "button" and args
    ]
    assert "Use suggested task" not in labels
    assert fake_st.session_state["task_text"] == "clean this"
    rendered = _rendered_text(fake_st.calls)
    assert "Guidance:" not in rendered
    assert "Filter rows where amount is greater than 1000." not in rendered
    assert fake_st.session_state["result_preview"] is previous_preview
    assert fake_st.session_state["output_bytes"] == b"old"
    assert fake_st.session_state["output_file_name"] == "old.csv"
    assert fake_st.session_state["run_count"] == 3

def test_ai_rewrite_button_renders_after_task_input(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    labels = [
        str(args[0])
        for name, args, _kwargs in fake_st.calls
        if name in {"text_area", "button"}
    ]
    assert labels.index("Describe the transformation") < labels.index(
        "Improve task with AI"
    )
    assert labels.index("Improve task with AI") < labels.index("Generate")

def test_ai_rewrite_button_disabled_without_task_text(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(uploaded_file=uploaded, task_text="   ")
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert _button_disabled_by_label(fake_st.calls, "Improve task with AI") is True

def test_ai_rewrite_button_disabled_without_upload_context(monkeypatch) -> None:
    fake_st = FakeStreamlit(task_text="Keep large orders.")
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert _button_disabled_by_label(fake_st.calls, "Improve task with AI") is True

def test_ai_rewrite_not_called_without_explicit_click(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="Filter rows where amount is greater than 1000",
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path: _schema())
    monkeypatch.setattr(
        web.task_advisor,
        "advise_task",
        lambda _task_text, _schema: TaskAdvice(
            quality="good",
            missing_details=[],
            suggestions=[],
        ),
    )
    monkeypatch.setattr(
        web,
        "_task_rewriter_module",
        lambda: (_ for _ in ()).throw(
            AssertionError("rewrite_task must not be available without click")
        ),
    )

    web.main()

    assert fake_st.session_state["rewritten_task"] is None

def test_ai_rewrite_click_calls_advisor_and_rewriter_for_single_file(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="clean this",
        clicked_buttons={"Improve task with AI"},
    )
    previous_preview = pd.DataFrame({"old": [1]})
    fake_st.session_state.update(
        {
            "result_preview": previous_preview,
            "output_bytes": b"old",
            "output_file_name": "old.csv",
            "run_count": 3,
        }
    )
    seen: dict[str, object] = {}

    def on_rewrite_call(
        original_task: str,
        schema: SchemaReport | MultiFileSchemaReport,
        advice: TaskAdvice | None,
    ) -> None:
        seen["rewrite_original_task"] = original_task
        seen["rewrite_schema"] = schema
        seen["rewrite_advice"] = advice
        assert fake_st.session_state["rewrite_count"] == 1
        assert fake_st.session_state["last_rewrite_timestamp"] == 123.0

    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 123.0)
    monkeypatch.setattr(web, "build_prompt_coach_advice", lambda _state: None)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path: _schema())
    monkeypatch.setattr(
        web.task_advisor,
        "advise_task",
        lambda task_text, schema: (
            seen.update({"advice_task": task_text, "advice_schema": schema})
            or TaskAdvice(
                quality="too_vague",
                missing_details=["desired operation"],
                suggestions=["Describe the transformation."],
            )
        ),
    )
    monkeypatch.setattr(
        web,
        "_task_rewriter_module",
        lambda: _fake_rewriter_module(on_call=on_rewrite_call),
    )

    web.main()

    assert seen["advice_task"] == "clean this"
    assert isinstance(seen["advice_schema"], SchemaReport)
    assert seen["rewrite_original_task"] == "clean this"
    assert isinstance(seen["rewrite_schema"], SchemaReport)
    assert isinstance(seen["rewrite_advice"], TaskAdvice)
    assert fake_st.session_state["rewrite_count"] == 1
    assert fake_st.session_state["last_rewrite_timestamp"] == 123.0
    assert fake_st.session_state["rewritten_task"] == (
        "Filter rows where amount is greater than 1000."
    )
    assert fake_st.session_state["result_preview"] is previous_preview
    assert fake_st.session_state["output_bytes"] == b"old"
    assert fake_st.session_state["output_file_name"] == "old.csv"
    assert fake_st.session_state["run_count"] == 3
    assert "Filter rows where amount is greater than 1000." in _rendered_text(
        fake_st.calls
    )

def test_ai_rewrite_click_passes_multi_file_schema(monkeypatch) -> None:
    fake_st = FakeStreamlit(
        input_mode="Two files",
        first_uploaded_file=FakeUploadedFile("orders.csv", b"order_id,pid\n1,p1\n"),
        second_uploaded_file=FakeUploadedFile("products.csv", b"pid,name\np1,x\n"),
        first_logical_name="orders",
        second_logical_name="products",
        task_text="merge these files",
        clicked_buttons={"Improve task with AI"},
    )
    seen: dict[str, object] = {}

    def on_rewrite_call(
        _original_task: str,
        schema: SchemaReport | MultiFileSchemaReport,
        _advice: TaskAdvice | None,
    ) -> None:
        seen["schema"] = schema

    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 123.0)
    monkeypatch.setattr(web, "build_prompt_coach_advice", lambda _state: None)
    monkeypatch.setattr(
        web.schema_inspector,
        "inspect_many",
        lambda _specs: _multi_schema(),
    )
    monkeypatch.setattr(
        web.task_advisor,
        "advise_task",
        lambda _task_text, _schema: TaskAdvice(
            quality="needs_detail",
            missing_details=["join key"],
            suggestions=[],
        ),
    )
    monkeypatch.setattr(
        web,
        "_task_rewriter_module",
        lambda: _fake_rewriter_module(
            rewritten_task=(
                "Merge orders and products using pid with a left join."
            ),
            on_call=on_rewrite_call,
        ),
    )

    web.main()

    assert isinstance(seen["schema"], MultiFileSchemaReport)
    assert fake_st.session_state["rewritten_task"] == (
        "Merge orders and products using pid with a left join."
    )

def test_use_rewritten_task_updates_only_task_text(monkeypatch) -> None:
    previous_preview = pd.DataFrame({"old": [1]})
    fake_st = FakeStreamlit(
        task_text="clean this",
        clicked_buttons={"Use rewritten task"},
    )
    fake_st.session_state.update(
        {
            "rewritten_task": "Filter rows where amount is greater than 1000.",
            "result_preview": previous_preview,
            "output_bytes": b"old",
            "output_file_name": "old.csv",
            "run_count": 3,
        }
    )
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda *_args, **_kwargs: calls.append(_args),
    )

    web.main()

    assert fake_st.session_state["task_text"] == (
        "Filter rows where amount is greater than 1000."
    )
    assert fake_st.session_state["result_preview"] is previous_preview
    assert fake_st.session_state["output_bytes"] == b"old"
    assert fake_st.session_state["output_file_name"] == "old.csv"
    assert fake_st.session_state["run_count"] == 3
    assert calls == []

def test_user_can_ignore_rewritten_task_and_keep_original_task(monkeypatch) -> None:
    previous_preview = pd.DataFrame({"old": [1]})
    fake_st = FakeStreamlit(task_text="clean this")
    fake_st.session_state.update(
        {
            "rewritten_task": "Filter rows where amount is greater than 1000.",
            "result_preview": previous_preview,
            "output_bytes": b"old",
            "output_file_name": "old.csv",
        }
    )
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert fake_st.session_state["task_text"] == "clean this"
    assert fake_st.session_state["rewritten_task"] == (
        "Filter rows where amount is greater than 1000."
    )
    assert fake_st.session_state["result_preview"] is previous_preview
    assert fake_st.session_state["output_bytes"] == b"old"
    assert fake_st.session_state["output_file_name"] == "old.csv"

def test_ai_rewrite_does_not_call_generate_pipeline_helpers(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="clean this",
        clicked_buttons={"Improve task with AI"},
    )

    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 123.0)
    monkeypatch.setattr(web, "build_prompt_coach_advice", lambda _state: None)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path: _schema())
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
        web.prompt_builder,
        "build",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("prompt_builder.build must not be called")
        ),
    )
    monkeypatch.setattr(
        web.retry_handler,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("retry_handler.run must not be called")
        ),
    )
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("run_uploaded_task must not be called")
        ),
    )

    web.main()

    assert fake_st.session_state["output_bytes"] is None
    assert fake_st.session_state["run_count"] == 0

def test_ai_rewrite_error_is_concise_and_redacted(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="clean this",
        clicked_buttons={"Improve task with AI"},
    )

    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 123.0)
    monkeypatch.setattr(web, "build_prompt_coach_advice", lambda _state: None)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path: _schema())
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

    web.main()

    rendered = _rendered_text(fake_st.calls)
    assert fake_st.session_state["rewrite_error_message"] == (
        "Could not improve the task. Check provider configuration and try again."
    )
    assert "Could not improve the task." in rendered
    assert "Traceback" not in rendered
    assert "sk-ant" not in rendered

def test_provider_failure_after_accepted_rewrite_keeps_count(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="clean this",
        clicked_buttons={"Improve task with AI"},
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 200.0)
    monkeypatch.setattr(web, "build_prompt_coach_advice", lambda _state: None)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path: _schema())
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
        lambda: _fake_rewriter_module(error=FakeRewriteError("provider failed")),
    )

    web.main()

    assert fake_st.session_state["rewrite_count"] == 1
    assert fake_st.session_state["last_rewrite_timestamp"] == 200.0
    assert fake_st.session_state["rewrite_error_message"] == (
        "Could not improve the task. Check provider configuration and try again."
    )

def test_rewrite_cooldown_blocks_without_provider_or_count(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="clean this",
        clicked_buttons={"Improve task with AI"},
    )
    fake_st.session_state["rewrite_count"] = 2
    fake_st.session_state["last_rewrite_timestamp"] = 100.0
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 101.0)
    monkeypatch.setattr(
        web,
        "_task_rewriter_module",
        lambda: (_ for _ in ()).throw(
            AssertionError("rewrite provider must not be called")
        ),
    )

    web.main()

    assert fake_st.session_state["rewrite_count"] == 2
    assert fake_st.session_state["last_rewrite_timestamp"] == 100.0
    assert fake_st.session_state["rewrite_error_message"] == (
        "Please wait 2.0s before improving the task again."
    )

def test_rewrite_limit_disables_without_provider_or_count(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="clean this",
        clicked_buttons={"Improve task with AI"},
    )
    fake_st.session_state["rewrite_count"] = web.MAX_REWRITES_PER_SESSION
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "_task_rewriter_module",
        lambda: (_ for _ in ()).throw(
            AssertionError("rewrite provider must not be called")
        ),
    )

    web.main()

    assert _button_disabled_by_label(fake_st.calls, "Improve task with AI") is True
    assert fake_st.session_state["rewrite_count"] == web.MAX_REWRITES_PER_SESSION
    assert fake_st.session_state["rewrite_error_message"] == (
        "Rewrite limit reached for this session."
    )

def test_rewrite_limit_and_cooldown_do_not_block_generate(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    fake_st.session_state["rewrite_count"] = web.MAX_REWRITES_PER_SESSION
    fake_st.session_state["last_rewrite_timestamp"] = 100.0
    calls: list[str] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 200.0)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda _file_bytes, _suffix, _task_text, uploaded_file_name=None, audit_metadata=None: (
            calls.append("generate")
            or (
                web.ExecutionResult(success=True),
                b"order_id,total\n1,10\n",
                web.derive_output_file_name(uploaded_file_name, ".csv"),
            )
        ),
    )

    web.main()

    assert calls == ["generate"]
    assert fake_st.session_state["run_count"] == 1
    assert fake_st.session_state["rewrite_count"] == web.MAX_REWRITES_PER_SESSION

def test_generate_run_count_does_not_affect_rewrite_count(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    fake_st.session_state["rewrite_count"] = 4
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 50.0)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda _file_bytes, _suffix, _task_text, uploaded_file_name=None, audit_metadata=None: (
            web.ExecutionResult(success=True),
            b"order_id,total\n1,10\n",
            web.derive_output_file_name(uploaded_file_name, ".csv"),
        ),
    )

    web.main()

    assert fake_st.session_state["run_count"] == 1
    assert fake_st.session_state["rewrite_count"] == 4

def test_generate_run_limit_does_not_block_ai_rewrite(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="clean this",
        clicked_buttons={"Improve task with AI"},
    )
    fake_st.session_state["run_count"] = web.MAX_RUNS_PER_SESSION
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 600.0)
    monkeypatch.setattr(web, "build_prompt_coach_advice", lambda _state: None)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path: _schema())
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

    web.main()

    assert fake_st.session_state["run_count"] == web.MAX_RUNS_PER_SESSION
    assert fake_st.session_state["rewrite_count"] == 1
    assert fake_st.session_state["last_rewrite_timestamp"] == 600.0
    assert fake_st.session_state["rewritten_task"] == (
        "Filter rows where amount is greater than 1000."
    )
