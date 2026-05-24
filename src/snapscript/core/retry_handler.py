'''
Streamlit / CLI
  -> schema_inspector.inspect(...)
  -> prompt_builder.build(...)
      -> PromptPayload
  -> retry_handler.run(...) # main entry for code generation + execution with retry logic
      -> code_generator.generate(...)
      -> safety_checker.check(...)
      -> execution_backend.execute(...)
          -> sandbox_executor or docker_sandbox_executor

Files:
- schema_inspector.py        -> read input file schema
- prompt_builder.py          -> create prompt
- code_generator.py          -> call LLM to generate code
- safety_checker.py          -> check generated code for safety issues
- execution_backend.py       -> select subprocess / Docker executor
- sandbox_executor.py        -> subprocess execution
- docker_sandbox_executor.py -> Docker execution
'''

from __future__ import annotations

from pathlib import Path

from snapscript.config import AppConfig
from snapscript.core import code_generator, execution_backend, safety_checker
from snapscript.core.models import ExecutionResult, GeneratedScript, PromptPayload


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
RETRY_PROMPT_PATH = PROMPT_DIR / "retry.txt"
MAX_MODEL_CALLS = 3 # 1. ori prompt, 2. retry with same model, 3. retry with fallback model (claude opus-4)


def run(prompt: PromptPayload, input_path: Path, output_path: Path) -> ExecutionResult:
    config = AppConfig()
    max_model_calls = min(config.max_retries + 1, MAX_MODEL_CALLS)
    current_prompt = prompt
    last_result: ExecutionResult | None = None

    for call_number in range(max_model_calls):
        model = (
            config.fallback_model # fallback model is claude-opus-4-20250514
            if call_number > 0 and call_number == max_model_calls - 1
            else None
        )
        # generate code with the current prompt and LLM model,
        #   if API key is invalid, this will raise an exception and skip retries
        # if model = None, use default model, else use fallback model
        generated = code_generator.generate(current_prompt, model=model)

        safety_result = safety_checker.check(generated.code)
        if not safety_result.is_safe:
            return _safety_failure(safety_result.violations)

        # subprocess -> sandbox_executor.execute(...)
        # docker     -> docker_sandbox_executor.execute(...)
        result = execution_backend.execute(
            generated.code,
            input_path,
            output_path,
            config,
        )
        last_result = result
        # if execution is successful, return the result immediately without retrying
        if result.success:
            return result
        # if this was the last allowed attempt, return the result without retrying
        if call_number == max_model_calls - 1:
            return result
        # not every failure should trigger a retry, for example if the error is a timeout or no stderr message, 
        #   it's unlikely that retrying will help, so we can skip retries in those cases
        if not _should_retry_execution(result):
            return result # return the failure result without retrying

        # build retry prompt with the original system prompt and user prompt, 
        #   plus the previous error message and the previously generated code
        current_prompt = _build_retry_prompt(prompt, result.stderr, generated)
    
    # if max_model_calls = 0
    if last_result is not None:
        return last_result
    return ExecutionResult(success=False, stderr="No generation attempt was made")


# result failed, not timeout, and stderr had error message, then we should retry
#   since retry prompt need error context
def _should_retry_execution(result: ExecutionResult) -> bool:
    if result.success:
        return False
    if _is_timeout(result):
        return False
    return bool(result.stderr.strip())


# timeout not retry
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
        # combine ori user prompt with retry context
        user_prompt=(
            f"{original_prompt.user_prompt}\n\n"
            "## Retry context\n"
            f"{retry_user_prompt}"
        ),
    )


# if is safety violation, return a failure ExecutionResult with the violation details in stderr
def _safety_failure(violations: list[str]) -> ExecutionResult:
    details = "\n".join(violations)
    return ExecutionResult(
        success=False,
        stderr=f"Safety violation: {details}",
        exit_code=1,
    )
