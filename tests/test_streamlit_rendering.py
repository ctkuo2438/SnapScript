import ast
import re
from pathlib import Path

import pandas as pd
import pytest

from snapscript.core.models import (
    ExecutionResult,
)
from snapscript.interfaces import web
from helpers.streamlit_helpers import (
    FakeStreamlit,
    FakeUploadedFile,
    _button_disabled,
    _has_placeholder_message,
)


@pytest.fixture(autouse=True)
def isolate_audit_log(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(web, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")


def test_app_entrypoint_only_delegates_to_web_main() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    ast.parse(source)

    assert "from snapscript.interfaces.web import main" in source
    assert 'if __name__ == "__main__":' in source
    assert "    main()" in source

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
