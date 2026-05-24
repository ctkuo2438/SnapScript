'''
pass the PromptPayload to the configured LLM provider, get the response, 
extract the generated code, validate it, and return a GeneratedScript.

PromptPayload
  -> Claude API call
  -> raw response
  -> cleaned Python code
  -> GeneratedScript

Streamlit / CLI
-> schema_inspector.inspect(...)
    -> SchemaReport
-> prompt_builder.build(...)
    -> PromptPayload(system_prompt, user_prompt)
-> retry_handler.run(...)
    -> code_generator.generate(...)
'''

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
    config = AppConfig() # default_model is "claude-sonnet-4-20250514", fallback_model is "claude-opus-4-20250514"
    provider = config.llm_provider.lower()
    selected_model = model or config.default_model

    if provider != "anthropic":
        raise UnsupportedProviderError(f"Unsupported LLM provider: {config.llm_provider}")

    # call the llm provider with the system and user prompts, get the raw response object
    response = _call_provider(prompt, selected_model, config)
    raw_response = _extract_text(response) # string
    code = _clean_python_code(raw_response)
    # validate that the extracted code is valid Python syntax, without executing it
    _validate_python(code)

    return GeneratedScript(
        code=code,
        raw_response=raw_response,
        model=selected_model,
        input_tokens=_usage_value(response, "input_tokens"),
        output_tokens=_usage_value(response, "output_tokens"),
    )


# call the LLM provider with the system and user prompts, return the raw response object
def _call_provider(prompt: PromptPayload, model: str, config: AppConfig) -> Any:
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


# extract the text content from the provider response, Anthropic response's content is a list of blocks
#   we concatenate the text from all blocks to get the full response text
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


# clean the raw response to extract just the Python code, removing any leading or trailing prose, and any code fencing
def _clean_python_code(raw_response: str) -> str:
    fenced = _extract_fenced_code(raw_response)
    candidate = fenced if fenced is not None else raw_response
    lines = candidate.strip().splitlines() # split into lines for further processing
    lines = _drop_leading_prose(lines)
    lines = _drop_trailing_prose(lines)
    code = "\n".join(lines).strip()
    if not code:
        raise EmptyProviderResponseError("Provider returned no Python code")
    return code


# extract the first fenced code block from the response, ```python ... ``` code fence
def _extract_fenced_code(raw_response: str) -> str | None:
    match = re.search(
        r"```(?:python|py)?\s*(.*?)```",
        raw_response,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return None
    return match.group(1)


# heuristically drop any leading lines that don't look like Python code
def _drop_leading_prose(lines: list[str]) -> list[str]:
    for index, line in enumerate(lines):
        if _looks_like_python_start(line):
            return lines[index:]
    return lines


# heuristically drop any trailing lines that don't look like Python code,
#   by checking from the end of the lines backwards and looking for the last point 
#   where the code is still valid Python
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


# heuristically determine if a line looks like the start of Python code,
#   by checking for common Python keywords and syntax patterns
'''
Ex: 
    Here is the pandas script: # remove this leading prose
    from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
    import pandas as pd
'''
def _looks_like_python_start(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith(("from ", "import ", "def ", "class ", "if ", "for "))
        or stripped.startswith(("while ", "try:", "with ", "print("))
        or "=" in stripped
    )


def _validate_python(code: str) -> None:
    try:
        # use ast.parse to check if the code is valid Python syntax, without executing it
        ast.parse(code)
    except SyntaxError as exc:
        raise InvalidGeneratedCodeError("Generated code is not valid Python") from exc


def _usage_value(response: Any, field_name: str) -> int:
    # Anthropic response has a usage attribute with input_tokens and output_tokens fields
    usage = getattr(response, "usage", None)
    value = getattr(usage, field_name, 0)
    if isinstance(value, int):
        return value
    return 0
