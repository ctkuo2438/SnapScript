"""Category-based messages with bounded, plain-text secret redaction."""
from collections.abc import Iterable
import os
import re

from snapscript.core.audit_logger import redact_secret_values
from snapscript.core.models import ErrorCategory, ExecutionResult


ERROR_MAX_CHARS = 2000
GENERIC_ERROR_MESSAGE = "Something went wrong."
PROVIDER_ERROR_MESSAGE = "Provider call failed. Check your API key or provider configuration."
SAFETY_ERROR_MESSAGE = "Generated code was rejected by the safety checker."
SANDBOX_ERROR_MESSAGE = "Execution failed in the sandbox."
ERROR_MESSAGES: dict[ErrorCategory, str] = {
    "provider_authentication": "Provider authentication failed. Set ANTHROPIC_API_KEY or check its value.",
    "provider_permission": "The API key lacks permission to use this model. Check provider access.",
    "provider_not_found": "The provider model was not found or is unavailable to this API key. Check the configured model.",
    "provider_bad_request": "The provider rejected the request. Check model parameters and input limits.",
    "provider_configuration": "Check the configured provider and model.",
    "provider_rate_limit": "Provider rate limit reached. Try again later.",
    "provider_timeout": "The provider request timed out. Try again later.",
    "provider_failure": PROVIDER_ERROR_MESSAGE,
    "safety_violation": SAFETY_ERROR_MESSAGE,
    "sandbox_failure": SANDBOX_ERROR_MESSAGE,
    "timeout": "Execution time limit exceeded.",
    "capture_limit": "Execution exceeded the output capture limit.",
    "output_limit": "Output exceeds the configured size limit.",
    "output_empty": "Output is empty.",
    "output_commit": "Could not commit the output file.",
    "workspace_failure": "Could not prepare the execution workspace.",
}


def safe_error_text(message: object, max_chars: int = ERROR_MAX_CHARS, secrets: Iterable[str] = ()) -> str:
    text = str(message or "").strip()
    if "Traceback (most recent call last):" in text:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = lines[-1] if lines else "Operation failed"
    for secret in (*secrets, os.environ.get("ANTHROPIC_API_KEY", "")):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = redact_secret_values(text)
    text = re.sub(r"(?:(?:/private)?/tmp|/var/folders)/[^\s'\",;:]+", "[path]", text)
    return (text or "Operation failed")[:max_chars]


def format_error(category: ErrorCategory, message: object = None, max_chars: int | None = None) -> str:
    limit = ERROR_MAX_CHARS if max_chars is None else max_chars
    prefix = ERROR_MESSAGES.get(category)
    if category.startswith("provider_") or category == "safety_violation":
        text = prefix or PROVIDER_ERROR_MESSAGE
    elif not str(message or "").strip():
        text = prefix or GENERIC_ERROR_MESSAGE
    else:
        summary = safe_error_text(message, limit + 1)
        text = f"{prefix} Summary: {summary}" if prefix else summary
    if len(text) > limit:
        suffix = "... [truncated]"
        return (text[:max(0, limit - len(suffix))] + suffix)[:limit]
    return text


def exception_category(exc: Exception) -> ErrorCategory:
    return getattr(exc, "category", None) or "unknown_failure"


def format_execution_error(result: ExecutionResult) -> str:
    return format_error(result.error_category or "sandbox_failure", result.stderr.strip() or result.stdout.strip())


def format_exception_error(exc: Exception) -> str:
    return format_error(exception_category(exc), f"{type(exc).__name__}: {exc}")
