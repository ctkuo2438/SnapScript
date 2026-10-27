"""Category-based user messages preserve bounded, redacted diagnostics."""
import pytest

from snapscript.core import audit_logger
from snapscript.core.models import ExecutionResult
from snapscript.interfaces import errors


@pytest.mark.parametrize("category,expected", [
    ("provider_authentication", "ANTHROPIC_API_KEY"),
    ("provider_not_found", "model"),
    ("provider_bad_request", "request"),
    ("timeout", "time"),
])
def test_category_produces_actionable_message(category, expected):
    result = ExecutionResult(False, stderr="arbitrary diagnostic", error_category=category)
    assert expected in errors.format_execution_error(result)


def test_error_formatting_is_bounded_and_redacts_current_key(monkeypatch):
    key = "fixture-current-key"
    monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    result = ExecutionResult(False, stderr=f"ValueError: {key} " + "x" * 5000, error_category="sandbox_failure")
    message = errors.format_execution_error(result)
    assert key not in message
    assert "[REDACTED]" in message
    assert len(message) <= 2000


def test_error_message_does_not_guess_safety_from_text():
    result = ExecutionResult(False, stderr="Safety violation: column text", error_category="sandbox_failure")
    assert errors.format_execution_error(result).startswith("Execution failed in the sandbox.")


@pytest.mark.parametrize("exc", [PermissionError("disk"), OSError("disk"), ValueError("programming error")])
def test_untyped_errors_are_not_mislabeled_as_input(exc):
    assert errors.exception_category(exc) == "unknown_failure"


def test_upload_validation_sets_its_own_category():
    from snapscript.interfaces.web_inputs import validate_task_text
    with pytest.raises(ValueError) as captured:
        validate_task_text(" ")
    assert errors.exception_category(captured.value) == "input_validation"


@pytest.mark.parametrize("category", ["provider_authentication", "provider_timeout", "provider_rate_limit", "provider_failure"])
def test_rewrite_uses_the_same_provider_message(category):
    from snapscript.core.provider import ProviderCallError
    from snapscript.interfaces import web_assistant

    exc = ProviderCallError("token=private-fixture", category=category)
    message = web_assistant._format_task_rewrite_error(exc)
    assert errors.ERROR_MESSAGES[category] in message
    assert "Could not improve the task." in message
    assert "private-fixture" not in message


def test_rewrite_disk_failure_is_not_input_validation(monkeypatch):
    from unittest.mock import Mock
    from snapscript.config import AppConfig
    from snapscript.core import audit_logger
    from snapscript.interfaces import web_assistant

    events = []
    state = {"task_text": "Copy rows", "is_rewriting_task": True}
    monkeypatch.setattr(web_assistant, "build_task_rewrite_context", Mock(side_effect=PermissionError("token=fixture-secret")))
    monkeypatch.setattr(audit_logger, "write_audit_event_best_effort", lambda event, **kwargs: events.append(event))
    web_assistant.improve_task_with_ai(state, AppConfig())
    assert events[0]["error_category"] == "unknown_failure"
    assert events[0]["provider_called"] is False
    assert "fixture-secret" not in state["rewrite_error_message"]
    assert state["is_rewriting_task"] is False


def test_rewrite_context_and_summary_together_obey_error_limit():
    from snapscript.interfaces import web_assistant

    message = web_assistant._format_task_rewrite_error(PermissionError("token=private-fixture " + "x" * 5000))
    assert len(message) <= errors.ERROR_MAX_CHARS
    assert "private-fixture" not in message
    assert "[truncated]" in message


@pytest.mark.parametrize("name", ["token", "password", "secret", "api_key"])
def test_colon_secrets_are_redacted_in_ui_and_audit(name: str) -> None:
    message = f"ValueError: {name}: fixture-demo-value"
    expected = f"ValueError: {name}=[REDACTED]"

    assert errors.format_error("unknown_failure", message) == expected
    assert audit_logger.redact_secret_values(message) == expected


def test_truncate_error_text_caps_long_message() -> None:
    truncated = errors.safe_error_text("x" * 25, max_chars=10)

    assert truncated == "x" * 10


def test_format_user_error_removes_traceback_lines() -> None:
    formatted = errors.format_error("unknown_failure",
        "Traceback (most recent call last):\n"
        '  File "/private/tmp/snapscript/run.py", line 4, in <module>\n'
        "ValueError: bad input"
    )

    assert "Traceback" not in formatted
    assert 'File "/private/tmp' not in formatted
    assert formatted == "ValueError: bad input"


def test_format_user_error_uses_generic_message_for_blank_text() -> None:
    assert errors.format_error("unknown_failure", "  ") == "Something went wrong."


def test_format_execution_error_maps_provider_failure() -> None:
    message = errors.format_execution_error(
        ExecutionResult(
            success=False,
            stderr=(
                "ProviderCallError: ANTHROPIC_API_KEY="
                "sk-ant-api03-exampleSecret123"
            ),
            error_category="provider_failure",
        )
    )

    assert message == (
        "Provider call failed. Check your API key or provider configuration."
    )
    assert "sk-ant" not in message


def test_format_execution_error_maps_safety_failure() -> None:
    message = errors.format_execution_error(
        ExecutionResult(
            success=False,
            stderr="Safety violation: generated code rejected unsafe import os",
            error_category="safety_violation",
        )
    )

    assert message == "Generated code was rejected by the safety checker."


def test_format_execution_error_maps_sandbox_failure_with_safe_summary() -> None:
    message = errors.format_execution_error(
        ExecutionResult(
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
