"""One bounded Anthropic SDK boundary for generation and task rewriting."""
from __future__ import annotations

import time
from typing import Any

from anthropic import (
    Anthropic, APITimeoutError, AuthenticationError, BadRequestError,
    NotFoundError, PermissionDeniedError, RateLimitError,
)

from snapscript.config import AppConfig
from snapscript.core import prompt_builder
from snapscript.core.models import ErrorCategory, PromptPayload, ProviderCallMetrics, ProviderReply


class CodeGenerationError(Exception):
    """Safe message/metrics; candidate text is internal retry context, never logged."""

    def __init__(self, message: str, *, category: ErrorCategory = "provider_failure") -> None:
        super().__init__(message)
        self.category = category
        self.api_calls: list[ProviderCallMetrics] = []
        self.response_text = ""


class UnsupportedProviderError(CodeGenerationError):
    pass


class ProviderCallError(CodeGenerationError):
    pass


class EmptyProviderResponseError(CodeGenerationError):
    pass


def call(prompt: PromptPayload, model: str, config: AppConfig) -> ProviderReply:
    if config.llm_provider.lower() != "anthropic":
        raise UnsupportedProviderError(f"Unsupported LLM provider: {config.llm_provider}", category="provider_configuration")
    try:
        prompt_builder.validate_budget(prompt, config)
    except prompt_builder.PromptBudgetError as exc:
        raise CodeGenerationError(str(exc), category="input_validation") from None
    start = time.monotonic()
    try:
        with Anthropic(
            timeout=config.provider_timeout_seconds, max_retries=config.provider_max_retries,
        ) as client:
            if not client.api_key and not client.auth_token:
                raise ProviderCallError(
                    "Set ANTHROPIC_API_KEY before generating or rewriting a task",
                    category="provider_authentication",
                )
            parameters: dict[str, Any] = {
                "model": model, "max_tokens": config.max_tokens,
                "system": prompt.system_prompt,
                "messages": [{"role": "user", "content": prompt.user_prompt}],
            }
            if config.temperature is not None:
                parameters["temperature"] = config.temperature
            response = client.messages.create(**parameters)
    except CodeGenerationError:
        raise
    except Exception as exc:
        category = (
            "provider_timeout" if isinstance(exc, APITimeoutError) else
            "provider_rate_limit" if isinstance(exc, RateLimitError) else
            "provider_authentication" if isinstance(exc, AuthenticationError) else
            "provider_permission" if isinstance(exc, PermissionDeniedError) else
            "provider_not_found" if isinstance(exc, NotFoundError) else
            "provider_bad_request" if isinstance(exc, BadRequestError) else
            "provider_failure"
        )
        error = ProviderCallError("Provider call failed", category=category)
        error.api_calls = [ProviderCallMetrics("anthropic", model, latency_ms=_elapsed_ms(start))]
        raise error from None
    metrics = ProviderCallMetrics(
        provider="anthropic", model=getattr(response, "model", None) or model,
        input_tokens=_usage_value(response, "input_tokens"),
        output_tokens=_usage_value(response, "output_tokens"), latency_ms=_elapsed_ms(start),
    )
    text = extract_text(response)
    if not text:
        error = EmptyProviderResponseError("Provider returned an empty response")
        error.api_calls = [metrics]
        raise error
    return ProviderReply(text, metrics, getattr(response, "stop_reason", None))


def extract_text(response: Any) -> str:
    return "\n".join(
        block.text for block in getattr(response, "content", []) or []
        if isinstance(getattr(block, "text", None), str)
    ).strip()


def _usage_value(response: Any, name: str) -> int | None:
    value = getattr(getattr(response, "usage", None), name, None)
    return value if isinstance(value, int) else None


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
