from __future__ import annotations

import ast
import re
from typing import Any

from anthropic import Anthropic

from snapscript.config import AppConfig
from snapscript.core.models import GeneratedScript, PromptPayload


class CodeGenerationError(Exception):
    """Base error for code generation failures."""


class UnsupportedProviderError(CodeGenerationError):
    """Raised when the configured provider is not implemented."""


class ProviderCallError(CodeGenerationError):
    """Raised when the configured provider call fails."""


class EmptyProviderResponseError(CodeGenerationError):
    """Raised when the provider returns no usable text."""


class InvalidGeneratedCodeError(CodeGenerationError):
    """Raised when generated text is not valid Python syntax."""


def generate(prompt: PromptPayload, model: str | None = None) -> GeneratedScript:
    config = AppConfig()
    provider = config.llm_provider.lower()
    selected_model = model or config.default_model

    if provider != "anthropic":
        raise UnsupportedProviderError(f"Unsupported LLM provider: {config.llm_provider}")

    response = _call_provider(prompt, selected_model, config)
    raw_response = _extract_text(response)
    code = _clean_python_code(raw_response)
    _validate_python(code)

    return GeneratedScript(
        code=code,
        raw_response=raw_response,
        model=selected_model,
        input_tokens=_usage_value(response, "input_tokens"),
        output_tokens=_usage_value(response, "output_tokens"),
    )


def _call_provider(
    prompt: PromptPayload, model: str, config: AppConfig
) -> Any:
    try:
        client = Anthropic()
        return client.messages.create(
            model=model,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            system=prompt.system_prompt,
            messages=[{"role": "user", "content": prompt.user_prompt}],
        )
    except Exception as exc:
        raise ProviderCallError("Provider call failed") from exc


def _extract_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)

    raw_response = "\n".join(parts).strip()
    if not raw_response:
        raise EmptyProviderResponseError("Provider returned an empty response")
    return raw_response


def _clean_python_code(raw_response: str) -> str:
    fenced = _extract_fenced_code(raw_response)
    candidate = fenced if fenced is not None else raw_response
    lines = candidate.strip().splitlines()
    lines = _drop_leading_prose(lines)
    lines = _drop_trailing_prose(lines)
    code = "\n".join(lines).strip()
    if not code:
        raise EmptyProviderResponseError("Provider returned no Python code")
    return code


def _extract_fenced_code(raw_response: str) -> str | None:
    match = re.search(
        r"```(?:python|py)?\s*(.*?)```",
        raw_response,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return None
    return match.group(1)


def _drop_leading_prose(lines: list[str]) -> list[str]:
    for index, line in enumerate(lines):
        if _looks_like_python_start(line):
            return lines[index:]
    return lines


def _drop_trailing_prose(lines: list[str]) -> list[str]:
    for index in range(len(lines), 0, -1):
        candidate = "\n".join(lines[:index]).strip()
        if not candidate:
            continue
        try:
            ast.parse(candidate)
        except SyntaxError:
            continue
        return lines[:index]
    return lines


def _looks_like_python_start(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith(("from ", "import ", "def ", "class ", "if ", "for "))
        or stripped.startswith(("while ", "try:", "with ", "print("))
        or "=" in stripped
    )


def _validate_python(code: str) -> None:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        raise InvalidGeneratedCodeError("Generated code is not valid Python") from exc


def _usage_value(response: Any, field_name: str) -> int:
    usage = getattr(response, "usage", None)
    value = getattr(usage, field_name, 0)
    if isinstance(value, int):
        return value
    return 0
