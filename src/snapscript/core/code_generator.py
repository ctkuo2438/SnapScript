"""Generate complete Python code through the shared provider boundary."""
from __future__ import annotations

import ast
import re

from snapscript.config import AppConfig
from snapscript.core import provider
from snapscript.core.models import GeneratedScript, PromptPayload
# Retain the existing public error imports for callers of this module.
from snapscript.core.provider import (
    CodeGenerationError, EmptyProviderResponseError, ProviderCallError, UnsupportedProviderError,
)


class InvalidGeneratedCodeError(CodeGenerationError):
    """Raised when generated text is incomplete or invalid Python."""

    def __init__(self, message: str) -> None:
        super().__init__(message, category="generation_failure")


def generate(
    prompt: PromptPayload, model: str | None = None, config: AppConfig | None = None,
) -> GeneratedScript:
    config = config if config is not None else AppConfig()
    response = provider.call(prompt, model or config.default_model, config)
    try:
        if response.stop_reason == "max_tokens":
            raise InvalidGeneratedCodeError("Provider response was truncated before completion")
        code = _clean_python_code(response.text)
        _validate_python(code)
    except CodeGenerationError as exc:
        exc.api_calls = [response.metrics]
        exc.response_text = response.text
        raise
    return GeneratedScript(
        code=code, raw_response=response.text, model=response.metrics.model,
        input_tokens=response.metrics.input_tokens or 0,
        output_tokens=response.metrics.output_tokens or 0,
        api_call=response.metrics,
    )


def _clean_python_code(raw_response: str) -> str:
    match = re.search(
        r"```(?:python|py)?\s*(.*?)```", raw_response,
        flags=re.IGNORECASE | re.DOTALL,
    )
    code = (match.group(1) if match else raw_response).strip()
    if not code:
        raise EmptyProviderResponseError("Provider returned no Python code")
    return code


def _validate_python(code: str) -> None:
    try:
        ast.parse(code)
    except SyntaxError:
        raise InvalidGeneratedCodeError("Generated code is not valid Python") from None
