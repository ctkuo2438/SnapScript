"""Generate, check, and execute with at most three model attempts."""
from __future__ import annotations

from pathlib import Path

from snapscript.config import AppConfig
from snapscript.core._sandbox_files import validate_destination
from snapscript.core import (
    code_generator,
    execution_backend,
    safety_checker,
    schema_inspector,
)
from snapscript.core.models import (
    ExecutionResult,
    InputFileSpec,
    PromptPayload,
)


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
RETRY_PROMPT_PATH = PROMPT_DIR / "retry.txt"
MAX_MODEL_CALLS = 3


def run(
    prompt: PromptPayload,
    input_path: Path,
    output_path: Path,
    model: str | None = None,
    config: AppConfig | None = None,
) -> ExecutionResult:
    return _run_with_inputs(
        prompt,
        input_path,
        output_path,
        model=model,
        config=config,
    )


def run_many(
    prompt: PromptPayload,
    inputs: list[InputFileSpec],
    output_path: Path,
    model: str | None = None,
    config: AppConfig | None = None,
) -> ExecutionResult:
    try:
        validated_inputs = schema_inspector.validate_input_specs(inputs)
    except schema_inspector.SchemaInspectionError as exc:
        return ExecutionResult(
            success=False,
            stderr=str(exc),
            exit_code=1,
            error_category="input_validation",
        )
    return _run_with_inputs(
        prompt,
        validated_inputs,
        output_path,
        model=model,
        config=config,
    )


def _run_with_inputs(
    prompt: PromptPayload, input_path: Path | list[InputFileSpec], output_path: Path,
    model: str | None = None, config: AppConfig | None = None,
) -> ExecutionResult:
    config = config if config is not None else AppConfig()
    error = validate_destination(input_path, output_path, overwrite=config.overwrite_output)
    if error:
        return ExecutionResult(success=False, stderr=error, exit_code=1, error_category="input_validation")
    unavailable = execution_backend.preflight(config)
    if unavailable is not None:
        return unavailable
    max_calls = min(config.max_retries + 1, MAX_MODEL_CALLS)
    current_prompt = prompt
    api_calls = []
    for attempt in range(max_calls):
        selected_model = config.fallback_model if attempt > 0 and attempt == max_calls - 1 else model
        try:
            generated = code_generator.generate(current_prompt, model=selected_model, config=config)
        except code_generator.CodeGenerationError as exc:
            api_calls.extend(exc.api_calls)
            recoverable = isinstance(exc, (
                code_generator.InvalidGeneratedCodeError, code_generator.EmptyProviderResponseError,
            ))
            if not recoverable or attempt == max_calls - 1:
                exc.api_calls = list(api_calls)
                raise
            current_prompt = _build_retry_prompt(prompt, str(exc), exc.response_text)
            continue
        if generated.api_call is not None:
            api_calls.append(generated.api_call)
        safety = safety_checker.check(generated.code, config=config)
        if not safety.is_safe or not safety.ast_valid:
            result = _safety_failure(safety.violations)
        else:
            result = execution_backend.execute(generated.code, input_path, output_path, config=config)
        result.api_calls = list(api_calls)
        if not result.success and result.error_category is None:
            result.error_category = "sandbox_failure"
        if result.success or attempt == max_calls - 1 or not _should_retry_execution(result):
            return result
        current_prompt = _build_retry_prompt(prompt, result.stderr, generated.code)
    raise AssertionError("AppConfig must allow at least one model attempt")


def _should_retry_execution(result: ExecutionResult) -> bool:
    return not result.success and result.error_category in {"sandbox_failure", "output_validation"}


def _build_retry_prompt(
    original_prompt: PromptPayload,
    previous_error: str,
    previous_code: str,
) -> PromptPayload:
    template = RETRY_PROMPT_PATH.read_text(encoding="utf-8")
    retry_user_prompt = template.format(
        previous_error=previous_error,
        previous_code=previous_code,
    )
    return PromptPayload(
        system_prompt=original_prompt.system_prompt,
        user_prompt=(
            f"{original_prompt.user_prompt}\n\n"
            "## Retry context\n"
            f"{retry_user_prompt}"
        ),
    )


def _safety_failure(violations: list[str]) -> ExecutionResult:
    details = "\n".join(violations)
    return ExecutionResult(
        success=False,
        stderr=f"Safety violation: {details}",
        exit_code=1,
        error_category="safety_violation",
    )
