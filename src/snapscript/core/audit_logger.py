from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid


DEFAULT_AUDIT_LOG_PATH = Path("logs/snapscript_audit.jsonl")
AUDIT_INCLUDE_PROMPTS_ENV = "SNAPSCRIPT_AUDIT_INCLUDE_PROMPTS"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def redact_secret_values(value: str) -> str:
    redacted = re.sub(
        r"\b(?P<name>[A-Z0-9_]*(?:API[_-]?KEY|TOKEN|PASSWORD|SECRET))"
        r"\s*=\s*['\"]?[^\s'\",;]+['\"]?",
        lambda match: f"{match.group('name')}=[REDACTED]",
        value,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"\b(?P<name>api[_-]?key|token|password|secret)"
        r"\s*[:=]\s*['\"]?[^\s'\",;}]+['\"]?",
        lambda match: f"{match.group('name')}=[REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"\bBearer\s+sk-[A-Za-z0-9._-]+",
        "Bearer [REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"\bsk-ant-[A-Za-z0-9._-]+",
        "[REDACTED]",
        redacted,
    )
    return re.sub(
        r"\bsk-[A-Za-z0-9][A-Za-z0-9._-]{8,}",
        "[REDACTED]",
        redacted,
    )


def safe_json_value(value: object) -> object:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return redact_secret_values(value)
    if isinstance(value, bytes):
        return {"sha256": sha256_bytes(value), "size_bytes": len(value)}
    if isinstance(value, Path):
        return redact_secret_values(str(value))
    if isinstance(value, dict):
        return {
            redact_secret_values(str(key)): safe_json_value(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list | tuple):
        return [safe_json_value(nested) for nested in value]
    return redact_secret_values(str(value))


def build_audit_event(
    *,
    timestamp: str | None = None,
    run_id: str | None = None,
    interface: str,
    provider: str,
    model: str,
    provider_called: bool,
    success: bool,
    duration_ms: int,
    input_file_name: str | None = None,
    input_file_bytes: bytes | None = None,
    task_text: str | None = None,
    schema_summary: object | None = None,
    prompt_text: str | None = None,
    generated_code: str | None = None,
    output_file_name: str | None = None,
    output_file_bytes: bytes | None = None,
    error_category: str | None = None,
    attempt_count: int | None = None,
    include_debug: bool | None = None,
    system_prompt: str | None = None,
    user_prompt: str | None = None,
) -> dict[str, object]:
    include_raw_debug = _include_debug_fields(include_debug)
    event: dict[str, object] = {
        "timestamp": timestamp or _utc_timestamp(),
        "run_id": run_id or uuid.uuid4().hex,
        "interface": interface,
        "provider": provider,
        "model": model,
        "provider_called": provider_called,
        "success": success,
        "duration_ms": duration_ms,
        "input_file_name": input_file_name,
        "input_file_size_bytes": (
            len(input_file_bytes) if input_file_bytes is not None else None
        ),
        "input_file_sha256": (
            sha256_bytes(input_file_bytes)
            if input_file_bytes is not None
            else None
        ),
        "task_text_sha256": sha256_text(task_text) if task_text else None,
        "schema_summary_sha256": (
            _sha256_json(schema_summary) if schema_summary is not None else None
        ),
        "prompt_sha256": sha256_text(prompt_text) if prompt_text else None,
        "generated_code_sha256": (
            sha256_text(generated_code) if generated_code else None
        ),
        "output_file_name": output_file_name,
        "output_file_size_bytes": (
            len(output_file_bytes) if output_file_bytes is not None else None
        ),
        "output_file_sha256": (
            sha256_bytes(output_file_bytes)
            if output_file_bytes is not None
            else None
        ),
        "error_category": error_category,
        "attempt_count": attempt_count,
    }

    if include_raw_debug:
        event["task_text"] = task_text
        event["system_prompt"] = system_prompt
        event["user_prompt"] = user_prompt
        event["generated_code"] = generated_code

    return safe_json_value(event)  # type: ignore[return-value]


def append_audit_event(
    event: dict[str, object],
    log_path: Path = DEFAULT_AUDIT_LOG_PATH,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    safe_event = safe_json_value(event)
    line = json.dumps(safe_event, sort_keys=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


def write_audit_event_best_effort(
    event: dict[str, object],
    log_path: Path = DEFAULT_AUDIT_LOG_PATH,
) -> bool:
    try:
        append_audit_event(event, log_path=log_path)
    except Exception:
        return False
    return True


def _include_debug_fields(include_debug: bool | None) -> bool:
    if include_debug is not None:
        return include_debug
    return os.environ.get(AUDIT_INCLUDE_PROMPTS_ENV) == "1"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_json(value: object) -> str:
    safe_value = safe_json_value(value)
    serialized = json.dumps(safe_value, sort_keys=True)
    return sha256_text(serialized)
