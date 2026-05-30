import ast
from io import BytesIO
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from snapscript.core.models import (
    ExecutionResult,
    InputFileSpec,
    MultiFileSchemaReport,
    PromptPayload,
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
    _has_placeholder_message,
    _multi_schema,
    _rendered_text,
    _schema,
)


EXPECTED_SESSION_DEFAULTS = {
    "input_mode": "Single file",
    "uploaded_file_name": None,
    "uploaded_file_bytes": None,
    "uploaded_file_suffix": None,
    "first_uploaded_file_name": None,
    "first_uploaded_file_bytes": None,
    "first_uploaded_file_suffix": None,
    "second_uploaded_file_name": None,
    "second_uploaded_file_bytes": None,
    "second_uploaded_file_suffix": None,
    "first_logical_name": "",
    "second_logical_name": "",
    "task_text": "",
    "result_preview": None,
    "output_bytes": None,
    "output_file_name": None,
    "error_message": None,
    "error_source": None,
    "rewritten_task": None,
    "rewrite_error_message": None,
    "is_rewriting_task": False,
    "rewrite_count": 0,
    "last_rewrite_timestamp": None,
    "run_count": 0,
    "last_run_timestamp": None,
    "is_running": False,
}


@pytest.fixture(autouse=True)
def isolate_audit_log(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(web, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")


def test_app_entrypoint_only_delegates_to_web_main() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    ast.parse(source)

    assert "from snapscript.interfaces.web import main" in source
    assert 'if __name__ == "__main__":' in source
    assert "    main()" in source


def test_initialize_session_state_sets_expected_defaults() -> None:
    state: dict[str, object] = {"run_count": 3}

    web.initialize_session_state(state)

    assert state["run_count"] == 3
    for key, expected in EXPECTED_SESSION_DEFAULTS.items():
        assert key in state
        if key != "run_count":
            assert state[key] == expected


def test_session_defaults_exactly_match_phase_2_plan_keys() -> None:
    assert set(web.SESSION_DEFAULTS) == set(EXPECTED_SESSION_DEFAULTS)


def test_clear_output_state_only_clears_output_fields() -> None:
    state: dict[str, object] = {
        "uploaded_file_name": "orders.csv",
        "uploaded_file_bytes": b"input",
        "uploaded_file_suffix": ".csv",
        "task_text": "Keep rows.",
        "result_preview": pd.DataFrame({"old": [1]}),
        "output_bytes": b"old",
        "output_file_name": "old.csv",
        "error_message": "old error",
        "run_count": 4,
        "last_run_timestamp": 123.0,
        "is_running": True,
    }

    web.clear_output_state(state)

    assert state["result_preview"] is None
    assert state["output_bytes"] is None
    assert state["output_file_name"] is None
    assert state["uploaded_file_name"] == "orders.csv"
    assert state["uploaded_file_bytes"] == b"input"
    assert state["uploaded_file_suffix"] == ".csv"
    assert state["task_text"] == "Keep rows."
    assert state["error_message"] == "old error"
    assert state["run_count"] == 4
    assert state["last_run_timestamp"] == 123.0
    assert state["is_running"] is True


def test_begin_accepted_run_clears_error_and_output_state() -> None:
    state: dict[str, object] = {
        "result_preview": pd.DataFrame({"old": [1]}),
        "output_bytes": b"old",
        "output_file_name": "old.csv",
        "error_message": "old error",
        "run_count": 2,
        "last_run_timestamp": 123.0,
        "is_running": False,
    }

    web.begin_accepted_run(state)

    assert state["result_preview"] is None
    assert state["output_bytes"] is None
    assert state["output_file_name"] is None
    assert state["error_message"] is None
    assert state["is_running"] is True
    assert state["run_count"] == 2
    assert state["last_run_timestamp"] == 123.0


def test_begin_accepted_run_with_timestamp_increments_run_count() -> None:
    state: dict[str, object] = {
        "result_preview": pd.DataFrame({"old": [1]}),
        "output_bytes": b"old",
        "output_file_name": "old.csv",
        "error_message": "old error",
        "run_count": 2,
        "last_run_timestamp": 123.0,
        "is_running": False,
    }

    web.begin_accepted_run(state, now=200.0)

    assert state["result_preview"] is None
    assert state["output_bytes"] is None
    assert state["output_file_name"] is None
    assert state["error_message"] is None
    assert state["is_running"] is True
    assert state["run_count"] == 3
    assert state["last_run_timestamp"] == 200.0


def test_mark_run_success_stores_output_and_clears_error() -> None:
    preview = pd.DataFrame({"order_id": [1]})
    state: dict[str, object] = {
        "result_preview": None,
        "output_bytes": None,
        "output_file_name": None,
        "error_message": "old error",
        "is_running": True,
    }

    web.mark_run_success(
        state,
        preview,
        b"order_id\n1\n",
        "orders_snapscript_output.csv",
    )

    assert state["result_preview"] is preview
    assert state["output_bytes"] == b"order_id\n1\n"
    assert state["output_file_name"] == "orders_snapscript_output.csv"
    assert state["error_message"] is None
    assert state["is_running"] is False


def test_mark_run_failure_clears_stale_output_and_stores_error() -> None:
    state: dict[str, object] = {
        "result_preview": pd.DataFrame({"old": [1]}),
        "output_bytes": b"old",
        "output_file_name": "old.csv",
        "error_message": None,
        "is_running": True,
    }

    web.mark_run_failure(state, "Execution failed")

    assert state["result_preview"] is None
    assert state["output_bytes"] is None
    assert state["output_file_name"] is None
    assert state["error_message"] == "Execution failed"
    assert state["is_running"] is False


def test_mark_validation_error_preserves_existing_output() -> None:
    preview = pd.DataFrame({"old": [1]})
    state: dict[str, object] = {
        "result_preview": preview,
        "output_bytes": b"old",
        "output_file_name": "old.csv",
        "error_message": None,
        "is_running": True,
    }

    web.mark_validation_error(state, "Task description is required.")

    assert state["result_preview"] is preview
    assert state["output_bytes"] == b"old"
    assert state["output_file_name"] == "old.csv"
    assert state["error_message"] == "Task description is required."
    assert state["is_running"] is False


def test_get_remaining_runs_never_returns_negative() -> None:
    assert web.get_remaining_runs(0) == 10
    assert web.get_remaining_runs(7) == 3
    assert web.get_remaining_runs(10) == 0
    assert web.get_remaining_runs(12) == 0
    assert web.get_remaining_runs(2, max_runs=4) == 2


def test_check_rate_limit_accepts_when_under_limit_without_recent_run() -> None:
    accepted, message = web.check_rate_limit(
        run_count=2,
        last_run_timestamp=None,
        now=100.0,
    )

    assert accepted is True
    assert message is None


def test_check_rate_limit_blocks_when_run_limit_reached() -> None:
    accepted, message = web.check_rate_limit(
        run_count=web.MAX_RUNS_PER_SESSION,
        last_run_timestamp=None,
        now=100.0,
    )

    assert accepted is False
    assert message == "Run limit reached for this session."


def test_check_rate_limit_blocks_when_cooldown_is_active() -> None:
    accepted, message = web.check_rate_limit(
        run_count=2,
        last_run_timestamp=100.0,
        now=102.25,
    )

    assert accepted is False
    assert message == "Please wait 2.8s before running again."


def test_check_rate_limit_accepts_when_cooldown_has_elapsed() -> None:
    accepted, message = web.check_rate_limit(
        run_count=2,
        last_run_timestamp=100.0,
        now=105.0,
    )

    assert accepted is True
    assert message is None


def test_get_remaining_rewrites_never_returns_negative() -> None:
    assert web.get_remaining_rewrites(0) == 10
    assert web.get_remaining_rewrites(7) == 3
    assert web.get_remaining_rewrites(10) == 0
    assert web.get_remaining_rewrites(12) == 0
    assert web.get_remaining_rewrites(2, max_rewrites=4) == 2


def test_check_rewrite_rate_limit_accepts_without_recent_rewrite() -> None:
    accepted, message = web.check_rewrite_rate_limit(
        rewrite_count=2,
        last_rewrite_timestamp=None,
        now=100.0,
    )

    assert accepted is True
    assert message is None


def test_check_rewrite_rate_limit_blocks_when_limit_reached() -> None:
    accepted, message = web.check_rewrite_rate_limit(
        rewrite_count=web.MAX_REWRITES_PER_SESSION,
        last_rewrite_timestamp=None,
        now=100.0,
    )

    assert accepted is False
    assert message == "Rewrite limit reached for this session."


def test_check_rewrite_rate_limit_blocks_during_cooldown() -> None:
    accepted, message = web.check_rewrite_rate_limit(
        rewrite_count=2,
        last_rewrite_timestamp=100.0,
        now=101.25,
    )

    assert accepted is False
    assert message == "Please wait 1.8s before improving the task again."


def test_check_rewrite_rate_limit_accepts_after_cooldown() -> None:
    accepted, message = web.check_rewrite_rate_limit(
        rewrite_count=2,
        last_rewrite_timestamp=100.0,
        now=103.0,
    )

    assert accepted is True
    assert message is None


def test_begin_accepted_rewrite_increments_without_clearing_output() -> None:
    preview = pd.DataFrame({"old": [1]})
    state: dict[str, object] = {
        "rewrite_error_message": "old error",
        "rewrite_count": 2,
        "last_rewrite_timestamp": 10.0,
        "is_rewriting_task": False,
        "result_preview": preview,
        "output_bytes": b"old",
        "output_file_name": "old.csv",
    }

    web.begin_accepted_rewrite(state, now=20.0)

    assert state["rewrite_error_message"] is None
    assert state["rewrite_count"] == 3
    assert state["last_rewrite_timestamp"] == 20.0
    assert state["is_rewriting_task"] is True
    assert state["result_preview"] is preview
    assert state["output_bytes"] == b"old"
    assert state["output_file_name"] == "old.csv"


def test_redact_error_text_redacts_anthropic_api_key() -> None:
    redacted = web.redact_error_text(
        "Authorization failed for Bearer sk-ant-api03-exampleSecret123"
    )

    assert "sk-ant" not in redacted
    assert redacted == "Authorization failed for Bearer [REDACTED]"


def test_redact_error_text_redacts_environment_assignment() -> None:
    redacted = web.redact_error_text(
        "ANTHROPIC_API_KEY=sk-ant-api03-exampleSecret123"
    )

    assert redacted == "ANTHROPIC_API_KEY=[REDACTED]"
    assert "sk-ant" not in redacted


def test_redact_error_text_redacts_secret_like_values() -> None:
    redacted = web.redact_error_text(
        "password=my-password token=abc123 secret=top-secret"
    )

    assert redacted == (
        "password=[REDACTED] token=[REDACTED] secret=[REDACTED]"
    )
    assert "my-password" not in redacted
    assert "abc123" not in redacted
    assert "top-secret" not in redacted


def test_truncate_error_text_caps_long_message() -> None:
    truncated = web.truncate_error_text("x" * 25, max_chars=10)

    assert truncated == "x" * 10 + "... [truncated]"


def test_format_user_error_removes_traceback_lines() -> None:
    formatted = web.format_user_error(
        "Traceback (most recent call last):\n"
        '  File "/private/tmp/snapscript/run.py", line 4, in <module>\n'
        "ValueError: bad input"
    )

    assert "Traceback" not in formatted
    assert 'File "/private/tmp' not in formatted
    assert formatted == "ValueError: bad input"


def test_format_user_error_uses_generic_message_for_blank_text() -> None:
    assert web.format_user_error("  ") == "Something went wrong."


def test_format_execution_error_maps_provider_failure() -> None:
    message = web.format_execution_error(
        web.ExecutionResult(
            success=False,
            stderr=(
                "ProviderCallError: ANTHROPIC_API_KEY="
                "sk-ant-api03-exampleSecret123"
            ),
        )
    )

    assert message == (
        "Provider call failed. Check your API key or provider configuration."
    )
    assert "sk-ant" not in message


def test_format_execution_error_maps_safety_failure() -> None:
    message = web.format_execution_error(
        web.ExecutionResult(
            success=False,
            stderr="Safety violation: generated code rejected unsafe import os",
        )
    )

    assert message == "Generated code was rejected by the safety checker."


def test_format_execution_error_maps_sandbox_failure_with_safe_summary() -> None:
    message = web.format_execution_error(
        web.ExecutionResult(
            success=False,
            stderr=(
                "Traceback (most recent call last):\n"
                '  File "/private/tmp/snapscript_web/run.py", line 1\n'
                "ValueError: bad transform"
            ),
            exit_code=1,
        )
    )

    assert message == (
        "Execution failed in the sandbox. Summary: "
        "ValueError: bad transform"
    )
    assert "Traceback" not in message
    assert "/private/tmp" not in message


def test_normalize_task_text_strips_whitespace() -> None:
    assert web.normalize_task_text("  Keep large orders. \n") == (
        "Keep large orders."
    )


def test_validate_task_text_accepts_nonblank_text() -> None:
    assert web.validate_task_text("  Keep large orders. ") == (
        "Keep large orders."
    )


@pytest.mark.parametrize("task_text", ["", "   ", "\n\t"])
def test_validate_task_text_rejects_blank_text(task_text: str) -> None:
    with pytest.raises(ValueError, match="Task description is required"):
        web.validate_task_text(task_text)


def test_can_generate_rejects_missing_upload() -> None:
    can_run, message = web.can_generate(
        {
            "uploaded_file_bytes": None,
            "uploaded_file_suffix": None,
            "task_text": "Keep large orders.",
            "run_count": 0,
        }
    )

    assert can_run is False
    assert message == "Upload a CSV or Excel file before generating."


def test_can_generate_rejects_blank_task_text() -> None:
    can_run, message = web.can_generate(
        {
            "uploaded_file_bytes": b"order_id,total\n1,10\n",
            "uploaded_file_suffix": ".csv",
            "task_text": "   ",
            "run_count": 0,
        }
    )

    assert can_run is False
    assert message == "Task description is required."


def test_can_generate_rejects_run_limit() -> None:
    can_run, message = web.can_generate(
        {
            "uploaded_file_bytes": b"order_id,total\n1,10\n",
            "uploaded_file_suffix": ".csv",
            "task_text": "Keep large orders.",
            "run_count": web.MAX_RUNS_PER_SESSION,
        }
    )

    assert can_run is False
    assert message == "Run limit reached for this session."


def test_can_generate_accepts_valid_upload_and_task_text() -> None:
    can_run, message = web.can_generate(
        {
            "uploaded_file_bytes": b"order_id,total\n1,10\n",
            "uploaded_file_suffix": ".csv",
            "task_text": "Keep large orders.",
            "run_count": 0,
        }
    )

    assert can_run is True
    assert message is None


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("orders.csv", ".csv"),
        ("orders.xlsx", ".xlsx"),
        ("orders.xls", ".xls"),
        ("ORDERS.CSV", ".csv"),
    ],
)
def test_validate_upload_suffix_accepts_supported_suffixes(
    file_name: str,
    expected: str,
) -> None:
    assert web.validate_upload_suffix(file_name) == expected


def test_validate_upload_suffix_rejects_unsupported_suffix() -> None:
    with pytest.raises(ValueError, match="Unsupported file type"):
        web.validate_upload_suffix("orders.txt")


def test_validate_upload_size_rejects_large_upload() -> None:
    with pytest.raises(ValueError, match="10 MB"):
        web.validate_upload_size(web.MAX_UPLOAD_BYTES + 1)


def test_store_uploaded_file_sets_name_suffix_and_bytes() -> None:
    state: dict[str, object] = {"error_message": "old error"}
    file_bytes = b"order_id,total\n1,10\n"

    web.store_uploaded_file(state, "Orders.CSV", file_bytes)

    assert state["uploaded_file_name"] == "Orders.CSV"
    assert state["uploaded_file_suffix"] == ".csv"
    assert state["uploaded_file_bytes"] == file_bytes
    assert state["error_message"] is None


def test_store_uploaded_file_rejects_invalid_data_before_storing() -> None:
    state: dict[str, object] = {
        "uploaded_file_name": "previous.csv",
        "uploaded_file_suffix": ".csv",
        "uploaded_file_bytes": b"previous",
        "error_message": None,
    }

    with pytest.raises(ValueError, match="Unsupported file type"):
        web.store_uploaded_file(state, "orders.txt", b"not,csv\n")

    assert state["uploaded_file_name"] is None
    assert state["uploaded_file_suffix"] is None
    assert state["uploaded_file_bytes"] is None
    assert state["error_message"] == "Unsupported file type: .txt"


def test_write_upload_to_temp_input_uses_internal_filename(
    tmp_path: Path,
) -> None:
    file_bytes = b"order_id,total\n1,10\n"

    input_path = web.write_upload_to_temp_input(
        tmp_path,
        file_bytes,
        ".csv",
    )

    assert input_path == tmp_path / "input.csv"
    assert input_path.read_bytes() == file_bytes
    assert input_path.resolve().parent == tmp_path.resolve()


@pytest.mark.parametrize(
    ("uploaded_file_name", "suffix", "expected"),
    [
        ("orders.csv", ".csv", "orders_snapscript_output.csv"),
        ("Orders.XLSX", ".xlsx", "Orders_snapscript_output.xlsx"),
        ("../../secret.csv", ".csv", "secret_snapscript_output.csv"),
        (None, ".csv", "snapscript_output.csv"),
        ("...csv", ".csv", "snapscript_output.csv"),
    ],
)
def test_derive_output_file_name_uses_safe_upload_stem(
    uploaded_file_name: str | None,
    suffix: str,
    expected: str,
) -> None:
    assert web.derive_output_file_name(uploaded_file_name, suffix) == expected


def test_load_output_preview_reads_csv_bytes() -> None:
    preview = web.load_output_preview(b"order_id,amount\n1,1500\n", ".csv")

    assert list(preview.columns) == ["order_id", "amount"]
    assert preview.to_dict(orient="records") == [
        {"order_id": 1, "amount": 1500}
    ]


def test_load_output_preview_limits_csv_rows() -> None:
    rows = ["row_id"] + [str(index) for index in range(150)]
    preview = web.load_output_preview(
        "\n".join(rows).encode("utf-8"),
        ".csv",
    )

    assert len(preview) == 100
    assert preview["row_id"].iloc[-1] == 99


def test_load_output_preview_reads_excel_bytes() -> None:
    buffer = BytesIO()
    pd.DataFrame({"order_id": [1], "amount": [1500]}).to_excel(
        buffer,
        index=False,
    )

    preview = web.load_output_preview(buffer.getvalue(), ".xlsx")

    assert preview.to_dict(orient="records") == [
        {"order_id": 1, "amount": 1500}
    ]


def test_path_like_upload_name_does_not_affect_temp_filename(
    tmp_path: Path,
) -> None:
    state: dict[str, object] = {}
    file_bytes = b"order_id,total\n1,10\n"
    web.store_uploaded_file(state, "../../secret.csv", file_bytes)

    input_path = web.write_upload_to_temp_input(
        tmp_path,
        bytes(state["uploaded_file_bytes"]),
        str(state["uploaded_file_suffix"]),
    )

    assert input_path == tmp_path / "input.csv"
    assert input_path.read_bytes() == file_bytes


def test_main_stores_valid_uploaded_file_without_pipeline_calls(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(uploaded_file=uploaded)
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert fake_st.session_state["uploaded_file_name"] == "orders.csv"
    assert fake_st.session_state["uploaded_file_suffix"] == ".csv"
    assert fake_st.session_state["uploaded_file_bytes"] == uploaded.getvalue()
    assert (
        "success",
        ("Uploaded orders.csv (20 bytes).",),
        {},
    ) in fake_st.calls
    assert not any(
        name == "download_button" for name, _args, _kwargs in fake_st.calls
    )


def test_main_displays_invalid_upload_error_without_pipeline_calls(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.txt", b"not,csv\n")
    fake_st = FakeStreamlit(uploaded_file=uploaded)
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert fake_st.session_state["uploaded_file_name"] is None
    assert fake_st.session_state["uploaded_file_suffix"] is None
    assert fake_st.session_state["uploaded_file_bytes"] is None
    assert fake_st.session_state["error_message"] == "Unsupported file type: .txt"
    assert ("error", ("Unsupported file type: .txt",), {}) in fake_st.calls
    assert not _has_placeholder_message(fake_st.calls)


def test_main_stores_task_text_in_session_state(monkeypatch) -> None:
    fake_st = FakeStreamlit(task_text="  Keep large orders. ")
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert fake_st.session_state["task_text"] == "  Keep large orders. "


def test_main_disables_generate_when_upload_is_missing(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(
        button_clicked=True,
        task_text="Keep large orders.",
    )
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert _button_disabled(fake_st.calls) is True
    assert not _has_placeholder_message(fake_st.calls)


def test_main_disables_generate_when_task_text_is_blank(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="   ",
    )
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert _button_disabled(fake_st.calls) is True
    assert not _has_placeholder_message(fake_st.calls)


def test_main_disables_generate_when_run_limit_reached(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(uploaded_file=uploaded, task_text="Keep rows.")
    fake_st.session_state["run_count"] = web.MAX_RUNS_PER_SESSION
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert _button_disabled(fake_st.calls) is True
    assert fake_st.session_state["error_message"] == (
        "Run limit reached for this session."
    )


def test_main_generate_click_validates_then_calls_pipeline_helper(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text=" Keep large orders. ",
    )
    calls: list[tuple[bytes, str, str]] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda file_bytes, suffix, task_text, uploaded_file_name=None, audit_metadata=None: (
            calls.append((file_bytes, suffix, task_text))
            or (
                web.ExecutionResult(success=True),
                b"ok\n",
                "snapscript_output.csv",
            )
        ),
    )

    web.main()

    assert _button_disabled(fake_st.calls) is False
    assert fake_st.session_state["task_text"] == " Keep large orders. "
    assert fake_st.session_state["error_message"] is None
    assert calls == [
        (
            b"order_id,total\n1,10\n",
            ".csv",
            " Keep large orders. ",
        )
    ]
    assert not _has_placeholder_message(fake_st.calls)


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
    assert "Merge orders and products using pid with a left join." in rendered
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


def test_use_suggested_task_updates_only_task_text(
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

    assert fake_st.session_state["task_text"] == (
        "Filter rows where amount is greater than 1000."
    )
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
    monkeypatch.setattr(web, "build_prompt_coach_advice", lambda _state: None)
    monkeypatch.setattr(web.schema_inspector, "inspect", lambda _path: _schema())
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
        web.audit_logger,
        "write_audit_event_best_effort",
        lambda _event, log_path=web.AUDIT_LOG_PATH: False,
    )

    web.main()

    assert fake_st.session_state["rewritten_task"] == (
        "Filter rows where amount is greater than 1000."
    )
    assert fake_st.session_state["rewrite_error_message"] is None


def test_run_uploaded_tasks_many_calls_multi_file_core_flow_with_temp_paths(
    monkeypatch,
) -> None:
    orders_bytes = b"order_id,pid\n1,p1\n"
    products_bytes = b"pid,product_name\np1,Keyboard\n"
    output_bytes = b"order_id,pid,product_name\n1,p1,Keyboard\n"
    calls: list[str] = []
    seen_specs: list[list[InputFileSpec]] = []

    def fake_inspect_many(specs: list[InputFileSpec]) -> MultiFileSchemaReport:
        calls.append("inspect_many")
        seen_specs.append(specs)
        assert [spec.name for spec in specs] == ["orders", "products"]
        assert [spec.display_filename for spec in specs] == [
            "orders.csv",
            "products.csv",
        ]
        assert specs[0].path.name == "input_1_orders.csv"
        assert specs[1].path.name == "input_2_products.csv"
        assert specs[0].path.read_bytes() == orders_bytes
        assert specs[1].path.read_bytes() == products_bytes
        return _multi_schema()

    def fake_build_many(
        task_text: str,
        multi_schema: MultiFileSchemaReport,
    ) -> PromptPayload:
        calls.append("build_many")
        assert task_text == "Merge orders and products."
        assert [file_schema.name for file_schema in multi_schema.files] == [
            "orders",
            "products",
        ]
        return PromptPayload(system_prompt="system", user_prompt="user")

    def fake_run_many(
        prompt: PromptPayload,
        specs: list[InputFileSpec],
        output_path: Path,
    ) -> ExecutionResult:
        calls.append("run_many")
        seen_specs.append(specs)
        assert prompt.user_prompt == "user"
        assert output_path.name == "output.csv"
        output_path.write_bytes(output_bytes)
        return ExecutionResult(success=True, output_files=[output_path])

    monkeypatch.setattr(web.schema_inspector, "inspect_many", fake_inspect_many)
    monkeypatch.setattr(web.prompt_builder, "build_many", fake_build_many)
    monkeypatch.setattr(web.retry_handler, "run_many", fake_run_many)

    result, returned_output, output_file_name = web.run_uploaded_tasks_many(
        first_file_bytes=orders_bytes,
        first_suffix=".csv",
        first_logical_name=" orders ",
        first_uploaded_file_name="orders.csv",
        second_file_bytes=products_bytes,
        second_suffix=".csv",
        second_logical_name="products",
        second_uploaded_file_name="products.csv",
        task_text=" Merge orders and products. ",
    )

    assert result.success is True
    assert returned_output == output_bytes
    assert output_file_name == "snapscript_output.csv"
    assert calls == ["inspect_many", "build_many", "run_many"]
    assert seen_specs[0] is seen_specs[1]


def test_main_two_file_generate_click_validates_then_calls_multi_file_helper(
    monkeypatch,
) -> None:
    orders = FakeUploadedFile("orders.csv", b"order_id,pid\n1,p1\n")
    products = FakeUploadedFile("products.csv", b"pid,product_name\np1,Keyboard\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        input_mode="Two files",
        first_uploaded_file=orders,
        second_uploaded_file=products,
        first_logical_name="orders",
        second_logical_name="products",
        task_text=" Merge orders and products. ",
    )
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_tasks_many",
        lambda **kwargs: (
            calls.append(
                (
                    str(kwargs["first_logical_name"]),
                    str(kwargs["second_logical_name"]),
                    str(kwargs["task_text"]),
                )
            )
            or (
                ExecutionResult(success=True),
                b"order_id,pid,product_name\n1,p1,Keyboard\n",
                "snapscript_output.csv",
            )
        ),
    )

    web.main()

    assert _button_disabled(fake_st.calls) is False
    assert calls == [("orders", "products", " Merge orders and products. ")]
    assert fake_st.session_state["first_uploaded_file_bytes"] == orders.getvalue()
    assert fake_st.session_state["second_uploaded_file_bytes"] == products.getvalue()
    assert fake_st.session_state["error_message"] is None


@pytest.mark.parametrize(
    ("first_name", "second_name", "second_file", "expected_error"),
    [
        ("orders", "products", None, "Upload both files before generating."),
        ("", "products", FakeUploadedFile("products.csv", b"x\n"), "Logical names are required"),
        ("orders", "", FakeUploadedFile("products.csv", b"x\n"), "Logical names are required"),
        ("orders", "orders", FakeUploadedFile("products.csv", b"x\n"), "Duplicate logical input name"),
        ("Orders", "products", FakeUploadedFile("products.csv", b"x\n"), "Invalid logical input name"),
    ],
)
def test_main_two_file_validation_blocks_before_pipeline_helper(
    monkeypatch,
    first_name: str,
    second_name: str,
    second_file: FakeUploadedFile | None,
    expected_error: str,
) -> None:
    fake_st = FakeStreamlit(
        button_clicked=True,
        input_mode="Two files",
        first_uploaded_file=FakeUploadedFile("orders.csv", b"x\n"),
        second_uploaded_file=second_file,
        first_logical_name=first_name,
        second_logical_name=second_name,
        task_text="Merge files.",
    )
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_tasks_many",
        lambda **kwargs: calls.append(kwargs),
    )

    web.main()

    assert _button_disabled(fake_st.calls) is True
    assert calls == []
    assert expected_error in str(fake_st.session_state["error_message"])


def test_main_two_file_unsupported_suffix_blocks_before_pipeline_helper(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(
        button_clicked=True,
        input_mode="Two files",
        first_uploaded_file=FakeUploadedFile("orders.csv", b"x\n"),
        second_uploaded_file=FakeUploadedFile("products.txt", b"x\n"),
        first_logical_name="orders",
        second_logical_name="products",
        task_text="Merge files.",
    )
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_tasks_many",
        lambda **kwargs: calls.append(kwargs),
    )

    web.main()

    assert _button_disabled(fake_st.calls) is True
    assert calls == []
    assert fake_st.session_state["error_message"] == "Unsupported file type: .txt"


def test_main_two_file_upload_without_generate_does_not_call_pipeline_helper(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(
        button_clicked=False,
        input_mode="Two files",
        first_uploaded_file=FakeUploadedFile("orders.csv", b"x\n"),
        second_uploaded_file=FakeUploadedFile("products.csv", b"x\n"),
        first_logical_name="orders",
        second_logical_name="products",
        task_text="Merge files.",
    )
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_tasks_many",
        lambda **kwargs: calls.append(kwargs),
    )

    web.main()

    assert calls == []


def test_main_single_file_mode_clears_stale_two_file_validation_error(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(
        input_mode="Single file",
        uploaded_file=None,
        task_text="Merge files.",
    )
    fake_st.session_state["error_message"] = "Upload both files before generating."
    fake_st.session_state["error_source"] = web.ERROR_SOURCE_VALIDATION
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert _button_disabled(fake_st.calls) is True
    assert fake_st.session_state["error_message"] is None
    assert fake_st.session_state["error_source"] is None


def test_main_two_file_cooldown_blocks_before_pipeline_helper(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(
        button_clicked=True,
        input_mode="Two files",
        first_uploaded_file=FakeUploadedFile("orders.csv", b"x\n"),
        second_uploaded_file=FakeUploadedFile("products.csv", b"x\n"),
        first_logical_name="orders",
        second_logical_name="products",
        task_text="Merge files.",
    )
    fake_st.session_state["run_count"] = 1
    fake_st.session_state["last_run_timestamp"] = 100.0
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 102.0)
    monkeypatch.setattr(
        web,
        "run_uploaded_tasks_many",
        lambda **kwargs: calls.append(kwargs),
    )

    web.main()

    assert calls == []
    assert fake_st.session_state["error_message"] == (
        "Please wait 3.0s before running again."
    )


def test_main_generate_click_increments_run_count_before_pipeline(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    fake_st.session_state["run_count"] = 2
    fake_st.session_state["last_run_timestamp"] = 10.0
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 20.0)

    def fake_run_uploaded_task(
        _file_bytes: bytes,
        _suffix: str,
        _task_text: str,
        uploaded_file_name: str | None = None,
        audit_metadata: dict[str, object] | None = None,
    ) -> tuple[web.ExecutionResult, bytes, str]:
        assert fake_st.session_state["run_count"] == 3
        assert fake_st.session_state["last_run_timestamp"] == 20.0
        assert fake_st.session_state["is_running"] is True
        return (
            web.ExecutionResult(success=True),
            b"order_id,total\n1,10\n",
            web.derive_output_file_name(uploaded_file_name, ".csv"),
        )

    monkeypatch.setattr(web, "run_uploaded_task", fake_run_uploaded_task)

    web.main()

    assert fake_st.session_state["run_count"] == 3
    assert fake_st.session_state["last_run_timestamp"] == 20.0


def test_main_generate_click_updates_last_run_timestamp(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 42.0)
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
    assert fake_st.session_state["last_run_timestamp"] == 42.0


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
    ) -> tuple[web.ExecutionResult, bytes, str]:
        if audit_metadata is not None:
            audit_metadata.update(
                {
                    "provider_called": True,
                    "schema_summary": {"columns": ["total"]},
                    "prompt_text": "system\n\nuser",
                    "generated_code": "print('ok')",
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
    assert event["model"] == "claude-sonnet-4-20250514"
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
    assert event["generated_code_sha256"] == web.audit_logger.sha256_text(
        "print('ok')"
    )
    assert event["output_file_name"] == "orders_snapscript_output.csv"
    assert event["output_file_sha256"] == web.audit_logger.sha256_bytes(
        b"order_id,total\n1,10\n"
    )
    assert "Keep rows." not in json.dumps(event)
    assert "order_id,total" not in json.dumps(event)


def test_main_accepted_failed_generate_writes_one_audit_event(
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
    monkeypatch.setattr(
        web.audit_logger,
        "write_audit_event_best_effort",
        lambda event, log_path=web.AUDIT_LOG_PATH: events.append(event) or True,
    )
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda _file_bytes, _suffix, _task_text, uploaded_file_name=None, audit_metadata=None: (
            web.ExecutionResult(
                success=False,
                stderr="RuntimeError: transform failed",
                exit_code=1,
            ),
            None,
            None,
        ),
    )

    web.main()

    assert len(events) == 1
    assert events[0]["success"] is False
    assert events[0]["error_category"] == "sandbox_failure"
    assert events[0]["output_file_sha256"] is None


def test_main_provider_exception_writes_provider_failure_audit_event(
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
    monkeypatch.setattr(
        web.audit_logger,
        "write_audit_event_best_effort",
        lambda event, log_path=web.AUDIT_LOG_PATH: events.append(event) or True,
    )

    def raise_provider_error(
        _file_bytes: bytes,
        _suffix: str,
        _task_text: str,
        uploaded_file_name: str | None = None,
        audit_metadata: dict[str, object] | None = None,
    ) -> tuple[web.ExecutionResult, None, None]:
        if audit_metadata is not None:
            audit_metadata["provider_called"] = True
        raise RuntimeError(
            "ProviderCallError: Bearer sk-ant-api03-exampleSecret123"
        )

    monkeypatch.setattr(web, "run_uploaded_task", raise_provider_error)

    web.main()

    assert len(events) == 1
    assert events[0]["success"] is False
    assert events[0]["provider_called"] is True
    assert events[0]["error_category"] == "provider_failure"
    assert "sk-ant" not in json.dumps(events[0])


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
        lambda _file_bytes, _suffix, _task_text, uploaded_file_name=None, audit_metadata=None: (
            web.ExecutionResult(success=True),
            b"order_id,total\n1,10\n",
            web.derive_output_file_name(uploaded_file_name, ".csv"),
        ),
    )

    web.main()

    assert fake_st.session_state["error_message"] is None
    assert fake_st.session_state["output_bytes"] == b"order_id,total\n1,10\n"


def test_main_cooldown_blocked_generate_does_not_call_pipeline(
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
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 102.0)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda *_args, **_kwargs: calls.append((_args, _kwargs)),
    )

    web.main()

    assert calls == []
    assert fake_st.session_state["run_count"] == 1
    assert fake_st.session_state["last_run_timestamp"] == 100.0
    assert fake_st.session_state["error_message"] == (
        "Please wait 3.0s before running again."
    )


def test_main_limit_blocked_generate_does_not_call_pipeline(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    fake_st.session_state["run_count"] = web.MAX_RUNS_PER_SESSION
    fake_st.session_state["last_run_timestamp"] = 100.0
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 120.0)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda *_args, **_kwargs: calls.append((_args, _kwargs)),
    )

    web.main()

    assert calls == []
    assert fake_st.session_state["run_count"] == web.MAX_RUNS_PER_SESSION
    assert fake_st.session_state["last_run_timestamp"] == 100.0
    assert fake_st.session_state["error_message"] == (
        "Run limit reached for this session."
    )


def test_main_renders_remaining_runs_display(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    fake_st.session_state["run_count"] = 4
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert (
        "caption",
        ("Remaining runs this session: 6",),
        {},
    ) in fake_st.calls


def test_main_sidebar_shows_default_sandbox_backend(monkeypatch) -> None:
    monkeypatch.delenv("SNAPSCRIPT_SANDBOX_BACKEND", raising=False)
    fake_st = FakeStreamlit()
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert ("sidebar.subheader", ("Runtime",), {}) in fake_st.calls
    assert (
        "sidebar.write",
        ("Sandbox backend: subprocess",),
        {},
    ) in fake_st.calls
    assert ("sidebar.caption", ("Use Docker backend:",), {}) in fake_st.calls
    assert (
        "sidebar.code",
        ("SNAPSCRIPT_SANDBOX_BACKEND=docker uv run streamlit run app.py",),
        {},
    ) in fake_st.calls


def test_main_sidebar_shows_docker_sandbox_backend(monkeypatch) -> None:
    monkeypatch.setenv("SNAPSCRIPT_SANDBOX_BACKEND", "docker")
    fake_st = FakeStreamlit()
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert (
        "sidebar.write",
        ("Sandbox backend: docker",),
        {},
    ) in fake_st.calls


def test_main_success_stores_preview_and_renders_download(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    output_bytes = b"order_id,total\n1,10\n"
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    fake_st.session_state["error_message"] = "old error"
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda _file_bytes, _suffix, _task_text, uploaded_file_name=None, audit_metadata=None: (
            web.ExecutionResult(success=True),
            output_bytes,
            web.derive_output_file_name(uploaded_file_name, ".csv"),
        ),
    )

    web.main()

    assert isinstance(fake_st.session_state["result_preview"], pd.DataFrame)
    assert fake_st.session_state["output_bytes"] == output_bytes
    assert fake_st.session_state["output_file_name"] == (
        "orders_snapscript_output.csv"
    )
    assert fake_st.session_state["error_message"] is None
    assert fake_st.session_state["is_running"] is False
    assert any(name == "dataframe" for name, _args, _kwargs in fake_st.calls)
    download_calls = [
        kwargs for name, _args, kwargs in fake_st.calls if name == "download_button"
    ]
    assert download_calls == [
        {
            "label": "Download output",
            "data": output_bytes,
            "file_name": "orders_snapscript_output.csv",
            "mime": "text/csv",
        }
    ]


def test_main_failed_generate_clears_preview_and_hides_download(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    fake_st.session_state.update(
        {
            "result_preview": pd.DataFrame({"old": [1]}),
            "output_bytes": b"old",
            "output_file_name": "old.csv",
        }
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda _file_bytes, _suffix, _task_text, uploaded_file_name=None, audit_metadata=None: (
            web.ExecutionResult(
                success=False,
                stderr="RuntimeError: transform failed",
                exit_code=1,
            ),
            None,
            None,
        ),
    )

    web.main()

    assert fake_st.session_state["result_preview"] is None
    assert fake_st.session_state["output_bytes"] is None
    assert fake_st.session_state["output_file_name"] is None
    assert fake_st.session_state["error_message"] == (
        "Execution failed in the sandbox. Summary: "
        "RuntimeError: transform failed"
    )
    assert not any(name == "download_button" for name, _args, _kwargs in fake_st.calls)


def test_main_exception_from_pipeline_redacts_secret(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    monkeypatch.setattr(web, "st", fake_st)

    def raise_provider_error(
        _file_bytes: bytes,
        _suffix: str,
        _task_text: str,
        uploaded_file_name: str | None = None,
        audit_metadata: dict[str, object] | None = None,
    ) -> tuple[web.ExecutionResult, None, None]:
        raise RuntimeError(
            "ProviderCallError: Bearer sk-ant-api03-exampleSecret123"
        )

    monkeypatch.setattr(web, "run_uploaded_task", raise_provider_error)

    web.main()

    assert fake_st.session_state["error_message"] == (
        "Provider call failed. Check your API key or provider configuration."
    )
    rendered_errors = [
        args[0] for name, args, _kwargs in fake_st.calls if name == "error"
    ]
    assert all("sk-ant" not in str(message) for message in rendered_errors)


def test_main_failed_execution_result_caps_long_stderr(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web, "ERROR_MAX_CHARS", 80)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda _file_bytes, _suffix, _task_text, uploaded_file_name=None, audit_metadata=None: (
            web.ExecutionResult(
                success=False,
                stderr="sandbox failure: " + ("x" * 200),
                exit_code=1,
            ),
            None,
            None,
        ),
    )

    web.main()

    error_message = str(fake_st.session_state["error_message"])
    assert len(error_message) <= 95
    assert error_message.endswith("... [truncated]")


def test_valid_new_upload_clears_previous_upload_error(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(uploaded_file=uploaded)
    fake_st.session_state["error_message"] = "Unsupported file type: .txt"
    fake_st.session_state["error_source"] = web.ERROR_SOURCE_UPLOAD
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert fake_st.session_state["uploaded_file_name"] == "orders.csv"
    assert fake_st.session_state["error_message"] is None
    assert fake_st.session_state["error_source"] is None


def test_valid_inputs_do_not_clear_execution_error(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    fake_st.session_state["error_message"] = "Execution failed in the sandbox."
    fake_st.session_state["error_source"] = web.ERROR_SOURCE_EXECUTION
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert _button_disabled(fake_st.calls) is False
    assert fake_st.session_state["error_message"] == (
        "Execution failed in the sandbox."
    )
    assert fake_st.session_state["error_source"] == web.ERROR_SOURCE_EXECUTION


def test_user_can_edit_task_after_failure_when_rate_limit_allows(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        uploaded_file=uploaded,
        task_text="Try a safer transform.",
    )
    fake_st.session_state.update(
        {
            "error_message": "Execution failed in the sandbox.",
            "run_count": 1,
            "last_run_timestamp": 1.0,
        }
    )
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert fake_st.session_state["task_text"] == "Try a safer transform."
    assert _button_disabled(fake_st.calls) is False


def test_no_full_traceback_is_rendered_from_failed_result(monkeypatch) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda _file_bytes, _suffix, _task_text, uploaded_file_name=None, audit_metadata=None: (
            web.ExecutionResult(
                success=False,
                stderr=(
                    "Traceback (most recent call last):\n"
                    '  File "/private/tmp/run.py", line 1\n'
                    "ValueError: failed"
                ),
                exit_code=1,
            ),
            None,
            None,
        ),
    )

    web.main()

    rendered_errors = [
        str(args[0]) for name, args, _kwargs in fake_st.calls if name == "error"
    ]
    assert rendered_errors
    assert all("Traceback" not in message for message in rendered_errors)
    assert all("/private/tmp" not in message for message in rendered_errors)


def test_uploading_file_alone_does_not_show_generation_placeholder(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(uploaded_file=uploaded)
    fake_st.session_state.update(
        {
            "result_preview": pd.DataFrame({"old": [1]}),
            "output_bytes": b"old",
            "output_file_name": "old.csv",
        }
    )
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert not _has_placeholder_message(fake_st.calls)
    assert isinstance(fake_st.session_state["result_preview"], pd.DataFrame)
    assert fake_st.session_state["output_bytes"] == b"old"
    assert fake_st.session_state["output_file_name"] == "old.csv"


def test_editing_task_text_alone_does_not_show_generation_placeholder(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(task_text="Keep large orders.")
    fake_st.session_state.update(
        {
            "result_preview": pd.DataFrame({"old": [1]}),
            "output_bytes": b"old",
            "output_file_name": "old.csv",
        }
    )
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert fake_st.session_state["task_text"] == "Keep large orders."
    assert not _has_placeholder_message(fake_st.calls)
    assert isinstance(fake_st.session_state["result_preview"], pd.DataFrame)
    assert fake_st.session_state["output_bytes"] == b"old"
    assert fake_st.session_state["output_file_name"] == "old.csv"


def test_main_renders_phase_2_skeleton_without_pipeline_calls(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    call_names = [name for name, _args, _kwargs in fake_st.calls]
    assert "title" in call_names
    assert "file_uploader" in call_names
    assert "text_area" in call_names
    assert "button" in call_names
    assert "caption" in call_names
    assert not _has_placeholder_message(fake_st.calls)


def test_web_imports_streamlit_and_retry_but_not_provider_or_sandbox() -> None:
    source = Path("src/snapscript/interfaces/web.py").read_text(encoding="utf-8")

    assert "import streamlit as st" in source
    assert "retry_handler.run(" in source
    assert "Anthropic" not in source
    assert "anthropic" not in source
    assert "code_generator" not in source
    assert "safety_checker" not in source
    assert "execution_backend" not in source
    assert "sandbox_executor" not in source
    assert ".generate(" not in source
    assert ".execute(" not in source


def test_core_has_no_streamlit_or_web_ui_dependency() -> None:
    disallowed = ("streamlit", "gradio", "fastapi", "flask", "dash")

    for path in Path("src/snapscript/core").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for term in disallowed:
            assert term not in source, f"{term} found in {path}"
        assert re.search(r"\bst\.", source) is None, f"st. found in {path}"
