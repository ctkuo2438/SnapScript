from __future__ import annotations

from pathlib import Path

from snapscript.config import AppConfig
from snapscript.core import code_generator, execution_backend, safety_checker
from snapscript.core.models import ExecutionResult, GeneratedScript, PromptPayload


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
RETRY_PROMPT_PATH = PROMPT_DIR / "retry.txt"
MAX_MODEL_CALLS = 3


def run(prompt: PromptPayload, input_path: Path, output_path: Path) -> ExecutionResult:
    config = AppConfig()
    max_model_calls = min(config.max_retries + 1, MAX_MODEL_CALLS)
    current_prompt = prompt
    last_result: ExecutionResult | None = None

    for call_number in range(max_model_calls):
        model = (
            config.fallback_model
            if call_number > 0 and call_number == max_model_calls - 1
            else None
        )
        # generate code with the current prompt and model
        # if API key is invalid, this will raise an exception and skip retries
        generated = code_generator.generate(current_prompt, model=model)

        safety_result = safety_checker.check(generated.code)
        if not safety_result.is_safe:
            return _safety_failure(safety_result.violations)

        result = execution_backend.execute(
            generated.code,
            input_path,
            output_path,
            config,
        )
        last_result = result
        if result.success:
            return result
        if call_number == max_model_calls - 1:
            return result
        if not _should_retry_execution(result):
            return result

        current_prompt = _build_retry_prompt(prompt, result.stderr, generated)

    if last_result is not None:
        return last_result
    return ExecutionResult(success=False, stderr="No generation attempt was made")


def _should_retry_execution(result: ExecutionResult) -> bool:
    if result.success:
        return False
    if _is_timeout(result):
        return False
    return bool(result.stderr.strip())


def _is_timeout(result: ExecutionResult) -> bool:
    return result.exit_code == -1 or "timed out" in result.stderr.lower()


def _build_retry_prompt(
    original_prompt: PromptPayload,
    previous_error: str,
    generated: GeneratedScript,
) -> PromptPayload:
    template = RETRY_PROMPT_PATH.read_text(encoding="utf-8")
    retry_user_prompt = template.format(
        previous_error=previous_error,
        previous_code=generated.code,
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
    )
