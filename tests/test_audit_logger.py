from __future__ import annotations

import json
from pathlib import Path

from snapscript.core import audit_logger


def test_sha256_bytes_returns_deterministic_hash() -> None:
    assert audit_logger.sha256_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223"
        "b00361a396177a9cb410ff61f20015ad"
    )


def test_sha256_text_returns_deterministic_hash() -> None:
    assert audit_logger.sha256_text("abc") == audit_logger.sha256_bytes(b"abc")


def test_redact_secret_values_redacts_api_key_like_values() -> None:
    redacted = audit_logger.redact_secret_values(
        "Bearer sk-ant-api03-secret ANTHROPIC_API_KEY=sk-ant-api03-secret "
        "password=my-password token=abc123 secret=top-secret"
    )

    assert "sk-ant" not in redacted
    assert "my-password" not in redacted
    assert "abc123" not in redacted
    assert "top-secret" not in redacted
    assert "Bearer [REDACTED]" in redacted
    assert "ANTHROPIC_API_KEY=[REDACTED]" in redacted
    assert "password=[REDACTED]" in redacted
    assert "token=[REDACTED]" in redacted
    assert "secret=[REDACTED]" in redacted


def test_append_audit_event_writes_valid_jsonl_and_creates_parent(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "nested" / "audit.jsonl"
    event = {"run_id": "run-1", "provider": "provider"}

    audit_logger.append_audit_event(event, log_path=log_path)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == event


def test_append_audit_event_appends_instead_of_overwriting(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "audit.jsonl"

    audit_logger.append_audit_event({"run_id": "run-1"}, log_path=log_path)
    audit_logger.append_audit_event({"run_id": "run-2"}, log_path=log_path)

    rows = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert rows == [{"run_id": "run-1"}, {"run_id": "run-2"}]


def test_write_audit_event_best_effort_does_not_raise_on_write_failure(
    tmp_path: Path,
) -> None:
    blocked_parent = tmp_path / "not_a_directory"
    blocked_parent.write_text("already a file", encoding="utf-8")

    written = audit_logger.write_audit_event_best_effort(
        {"run_id": "run-1"},
        log_path=blocked_parent / "audit.jsonl",
    )

    assert written is False


def test_build_audit_event_includes_safe_metadata_and_hashes() -> None:
    event = audit_logger.build_audit_event(
        timestamp="2026-05-19T00:00:00+00:00",
        run_id="run-1",
        interface="web",
        provider="provider",
        model="model",
        provider_called=True,
        success=True,
        duration_ms=123,
        input_file_name="orders.csv",
        input_file_bytes=b"order_id,amount\n1,1500\n",
        task_text="Keep large orders.",
        schema_summary={"columns": [{"name": "amount", "dtype": "int64"}]},
        prompt_text="system prompt\nuser prompt",
        generated_code="print('ok')",
        output_file_name="orders_output.csv",
        output_file_bytes=b"order_id,amount\n1,1500\n",
        attempt_count=2,
    )

    assert event["timestamp"] == "2026-05-19T00:00:00+00:00"
    assert event["run_id"] == "run-1"
    assert event["interface"] == "web"
    assert event["provider"] == "provider"
    assert event["model"] == "model"
    assert event["provider_called"] is True
    assert event["success"] is True
    assert event["duration_ms"] == 123
    assert event["input_file_name"] == "orders.csv"
    assert event["input_file_size_bytes"] == 23
    assert event["input_file_sha256"] == audit_logger.sha256_bytes(
        b"order_id,amount\n1,1500\n"
    )
    assert event["task_text_sha256"] == audit_logger.sha256_text(
        "Keep large orders."
    )
    assert event["schema_summary_sha256"] is not None
    assert event["prompt_sha256"] == audit_logger.sha256_text(
        "system prompt\nuser prompt"
    )
    assert event["generated_code_sha256"] == audit_logger.sha256_text(
        "print('ok')"
    )
    assert event["output_file_name"] == "orders_output.csv"
    assert event["output_file_size_bytes"] == 23
    assert event["output_file_sha256"] == audit_logger.sha256_bytes(
        b"order_id,amount\n1,1500\n"
    )
    assert event["attempt_count"] == 2


def test_build_audit_event_omits_raw_file_prompt_task_and_code_by_default() -> None:
    event = audit_logger.build_audit_event(
        timestamp="2026-05-19T00:00:00+00:00",
        run_id="run-1",
        interface="web",
        provider="provider",
        model="model",
        provider_called=True,
        success=True,
        duration_ms=123,
        input_file_bytes=b"customer,email\nAlice,alice@example.com\n",
        task_text="Keep Alice's rows.",
        prompt_text="Prompt with Alice",
        generated_code="print('Alice')",
        output_file_bytes=b"customer,email\nAlice,alice@example.com\n",
    )
    serialized = json.dumps(event, sort_keys=True)

    assert "Alice" not in serialized
    assert "alice@example.com" not in serialized
    assert "Prompt with Alice" not in serialized
    assert "print('Alice')" not in serialized
    assert "task_text" not in event
    assert "system_prompt" not in event
    assert "user_prompt" not in event
    assert "generated_code" not in event


def test_build_audit_event_debug_mode_can_include_redacted_debug_fields() -> None:
    event = audit_logger.build_audit_event(
        timestamp="2026-05-19T00:00:00+00:00",
        run_id="run-1",
        interface="web",
        provider="provider",
        model="model",
        provider_called=True,
        success=False,
        duration_ms=123,
        task_text="Filter rows with token=abc123",
        system_prompt="System Bearer sk-ant-api03-secret",
        user_prompt="User password=my-password",
        generated_code="API_KEY=sk-ant-api03-secret",
        include_debug=True,
    )

    assert event["task_text"] == "Filter rows with token=[REDACTED]"
    assert event["system_prompt"] == "System Bearer [REDACTED]"
    assert event["user_prompt"] == "User password=[REDACTED]"
    assert event["generated_code"] == "API_KEY=[REDACTED]"


def test_build_audit_event_debug_env_var_enables_debug_fields(
    monkeypatch,
) -> None:
    monkeypatch.setenv(audit_logger.AUDIT_INCLUDE_PROMPTS_ENV, "1")

    event = audit_logger.build_audit_event(
        timestamp="2026-05-19T00:00:00+00:00",
        run_id="run-1",
        interface="web",
        provider="provider",
        model="model",
        provider_called=True,
        success=True,
        duration_ms=123,
        task_text="Keep large orders.",
    )

    assert event["task_text"] == "Keep large orders."
