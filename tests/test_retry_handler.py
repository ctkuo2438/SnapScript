from pathlib import Path
import subprocess
import time
from unittest.mock import Mock

import pytest

from snapscript.config import AppConfig
from snapscript.core import _docker_runtime, code_generator, retry_handler, sandbox_executor
from snapscript.core._process import CaptureLimitExceeded
from snapscript.interfaces import cli
from snapscript.core.models import (
    ExecutionResult,
    GeneratedScript,
    InputFileSpec,
    PromptPayload,
    SafetyResult,
)


def _prompt() -> PromptPayload:
    return PromptPayload(
        system_prompt="system prompt",
        user_prompt="original user prompt",
    )


def _script(code: str, model: str = "model") -> GeneratedScript:
    return GeneratedScript(code=code, raw_response=code, model=model)


def _success() -> ExecutionResult:
    return ExecutionResult(success=True, stdout="ok", exit_code=0)


def _failure(stderr: str, exit_code: int = 1, category: str = "sandbox_failure") -> ExecutionResult:
    return ExecutionResult(success=False, stderr=stderr, exit_code=exit_code, error_category=category)


def _input_specs(tmp_path: Path) -> list[InputFileSpec]:
    return [
        InputFileSpec(name="orders", path=tmp_path / "orders.csv"),
        InputFileSpec(name="products", path=tmp_path / "products.csv"),
    ]


@pytest.mark.parametrize("error,category", [("Input validation: products missing column pid", "input_validation"), ("Output is empty", "output_empty")])
def test_run_does_not_retry_input_validation_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: str, category: str,
) -> None:
    calls = []

    def fake_generate(prompt, model=None, config=None):
        calls.append(prompt)
        return _script("print('validation')")

    monkeypatch.setattr(code_generator, "generate", fake_generate)
    monkeypatch.setattr(retry_handler.execution_backend, "execute", lambda *a, **k: _failure(error, category=category))

    result = retry_handler.run(_prompt(), tmp_path / "input.csv", tmp_path / "out.csv")

    assert result.success is False
    assert result.stderr == error
    assert len(calls) == 1


def test_run_rejects_source_output_before_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "input.csv"
    source.write_text("id\n1\n")

    def unexpected_generate(*args, **kwargs):
        pytest.fail("Source/output overlap must be rejected before generation")

    monkeypatch.setattr(code_generator, "generate", unexpected_generate)

    result = retry_handler.run(_prompt(), source, source)

    assert not result.success
    assert "overwrite" in result.stderr
    assert source.read_text() == "id\n1\n"


def test_run_retries_traceback_failures_and_uses_fallback_on_final_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated_calls: list[tuple[PromptPayload, str | None]] = []
    safety_codes: list[str] = []
    executed_codes: list[str] = []

    scripts = [_script("code v1"), _script("code v2"), _script("code v3")]
    executions = [
        _failure("Traceback (most recent call last):\nNameError: bad"),
        _failure("Traceback (most recent call last):\nKeyError: bad"),
        _success(),
    ]

    def fake_generate(
        prompt: PromptPayload,
        model: str | None = None,
        config: AppConfig | None = None,
    ) -> GeneratedScript:
        generated_calls.append((prompt, model))
        return scripts[len(generated_calls) - 1]

    def fake_check(code: str, config: AppConfig | None = None) -> SafetyResult:
        safety_codes.append(code)
        return SafetyResult(is_safe=True)

    def fake_execute(
        code: str,
        input_path: Path,
        output_path: Path,
        config: AppConfig | None = None,
    ) -> ExecutionResult:
        executed_codes.append(code)
        return executions[len(executed_codes) - 1]

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)
    monkeypatch.setattr(retry_handler.safety_checker, "check", fake_check)
    monkeypatch.setattr(retry_handler.execution_backend, "execute", fake_execute)
    monkeypatch.setattr(
        retry_handler,
        "AppConfig",
        lambda: AppConfig(default_model="default-model", fallback_model="fallback-model"),
    )

    result = retry_handler.run(_prompt(), tmp_path / "input.csv", tmp_path / "out.csv")

    assert result.success is True
    assert safety_codes == ["code v1", "code v2", "code v3"]
    assert executed_codes == ["code v1", "code v2", "code v3"]
    assert [model for _, model in generated_calls] == [None, None, "fallback-model"]
    assert len(generated_calls) == 3

    retry_prompt = generated_calls[1][0]
    final_retry_prompt = generated_calls[2][0]
    assert retry_prompt.system_prompt == "system prompt"
    assert final_retry_prompt.system_prompt == "system prompt"
    assert "original user prompt" in retry_prompt.user_prompt
    assert "original user prompt" in final_retry_prompt.user_prompt
    assert "Traceback (most recent call last)" in retry_prompt.user_prompt
    assert "NameError: bad" in retry_prompt.user_prompt
    assert "code v1" in retry_prompt.user_prompt
    assert "KeyError: bad" in final_retry_prompt.user_prompt
    assert "code v2" in final_retry_prompt.user_prompt


def test_run_retries_stderr_context_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def fake_generate(
        prompt: PromptPayload,
        model: str | None = None,
        config: AppConfig | None = None,
    ) -> GeneratedScript:
        nonlocal calls
        calls += 1
        return _script(f"code v{calls}")

    def fake_execute(
        code: str,
        input_path: Path,
        output_path: Path,
        config: AppConfig | None = None,
    ) -> ExecutionResult:
        if code == "code v1":
            return _failure("ValueError: bad data")
        return _success()

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code, config=None: SafetyResult(is_safe=True),
    )
    monkeypatch.setattr(retry_handler.execution_backend, "execute", fake_execute)

    result = retry_handler.run(_prompt(), tmp_path / "input.csv", tmp_path / "out.csv")

    assert result.success is True
    assert calls == 2


def test_run_does_not_retry_safety_violations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generate_calls = 0
    execute_calls = 0

    def fake_generate(
        prompt: PromptPayload,
        model: str | None = None,
        config: AppConfig | None = None,
    ) -> GeneratedScript:
        nonlocal generate_calls
        generate_calls += 1
        return _script("import os")

    def fake_execute(
        code: str,
        input_path: Path,
        output_path: Path,
        config: AppConfig | None = None,
    ) -> ExecutionResult:
        nonlocal execute_calls
        execute_calls += 1
        return _success()

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code, config=None: SafetyResult(
            is_safe=False,
            violations=["Blocked unsafe import: os"],
        ),
    )
    monkeypatch.setattr(retry_handler.execution_backend, "execute", fake_execute)

    result = retry_handler.run(_prompt(), tmp_path / "input.csv", tmp_path / "out.csv")

    assert result.success is False
    assert "Safety violation" in result.stderr
    assert "Blocked unsafe import: os" in result.stderr
    assert generate_calls == 1
    assert execute_calls == 0


def test_run_treats_ast_invalid_safety_result_as_failure_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execute_calls = 0

    def fake_execute(
        code: str,
        input_path: Path,
        output_path: Path,
        config: AppConfig | None = None,
    ) -> ExecutionResult:
        nonlocal execute_calls
        execute_calls += 1
        return _success()

    monkeypatch.setattr(
        retry_handler.code_generator,
        "generate",
        lambda _prompt, model=None, config=None: _script("x ="),
    )
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code, config=None: SafetyResult(
            is_safe=True,
            ast_valid=False,
            violations=["Syntax error"],
        ),
    )
    monkeypatch.setattr(retry_handler.execution_backend, "execute", fake_execute)

    result = retry_handler.run(_prompt(), tmp_path / "input.csv", tmp_path / "out.csv")

    assert result.success is False
    assert "Safety violation" in result.stderr
    assert "Syntax error" in result.stderr
    assert execute_calls == 0


def test_run_does_not_retry_timeouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generate_calls = 0

    def fake_generate(
        prompt: PromptPayload,
        model: str | None = None,
        config: AppConfig | None = None,
    ) -> GeneratedScript:
        nonlocal generate_calls
        generate_calls += 1
        return _script("while True: pass")

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code, config=None: SafetyResult(is_safe=True),
    )
    monkeypatch.setattr(
        retry_handler.execution_backend,
        "execute",
        lambda code, input_path, output_path, config=None: _failure(
            "Execution timed out", -1, category="timeout"
        ),
    )

    result = retry_handler.run(_prompt(), tmp_path / "input.csv", tmp_path / "out.csv")

    assert result.success is False
    assert "timed out" in result.stderr
    assert generate_calls == 1


@pytest.mark.parametrize(
    "error",
    [
        code_generator.ProviderCallError("Provider call failed"),
        code_generator.UnsupportedProviderError("Unsupported provider"),
    ],
)
def test_run_does_not_retry_provider_or_config_errors(
    error: code_generator.CodeGenerationError,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generate_calls = 0

    def fake_generate(
        prompt: PromptPayload,
        model: str | None = None,
        config: AppConfig | None = None,
    ) -> GeneratedScript:
        nonlocal generate_calls
        generate_calls += 1
        raise error

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)

    with pytest.raises(type(error)):
        retry_handler.run(_prompt(), tmp_path / "input.csv", tmp_path / "out.csv")

    assert generate_calls == 1


def test_run_caps_total_model_calls_at_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generate_calls = 0

    def fake_generate(
        prompt: PromptPayload,
        model: str | None = None,
        config: AppConfig | None = None,
    ) -> GeneratedScript:
        nonlocal generate_calls
        generate_calls += 1
        return _script(f"code v{generate_calls}")

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code, config=None: SafetyResult(is_safe=True),
    )
    monkeypatch.setattr(
        retry_handler.execution_backend,
        "execute",
        lambda code, input_path, output_path, config=None: _failure(
            "Traceback\nRuntimeError: bad"
        ),
    )

    result = retry_handler.run(_prompt(), tmp_path / "input.csv", tmp_path / "out.csv")

    assert result.success is False
    assert generate_calls == 3


def test_run_does_not_use_fallback_for_initial_call_when_retries_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models: list[str | None] = []

    def fake_generate(
        prompt: PromptPayload,
        model: str | None = None,
        config: AppConfig | None = None,
    ) -> GeneratedScript:
        models.append(model)
        return _script("code")

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code, config=None: SafetyResult(is_safe=True),
    )
    monkeypatch.setattr(
        retry_handler.execution_backend,
        "execute",
        lambda code, input_path, output_path, config=None: _success(),
    )
    monkeypatch.setattr(
        retry_handler,
        "AppConfig",
        lambda: AppConfig(max_retries=0, fallback_model="fallback-model"),
    )

    result = retry_handler.run(_prompt(), tmp_path / "input.csv", tmp_path / "out.csv")

    assert result.success is True
    assert models == [None]


def test_run_respects_passed_config_max_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generate_calls = 0

    def fake_generate(
        prompt: PromptPayload,
        model: str | None = None,
        config: AppConfig | None = None,
    ) -> GeneratedScript:
        nonlocal generate_calls
        generate_calls += 1
        return _script("code")

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code, config=None: SafetyResult(is_safe=True),
    )
    monkeypatch.setattr(
        retry_handler.execution_backend,
        "execute",
        lambda code, input_path, output_path, config=None: _failure(
            "Traceback\nRuntimeError: bad"
        ),
    )

    retry_handler.run(
        _prompt(),
        tmp_path / "input.csv",
        tmp_path / "out.csv",
        config=AppConfig(max_retries=0),
    )

    assert generate_calls == 1


def test_retry_handler_core_has_no_ui_dependencies() -> None:
    source = Path("src/snapscript/core/retry_handler.py").read_text()

    assert "argparse" not in source
    assert "rich" not in source
    assert "streamlit" not in source
    assert "sys.argv" not in source


def test_run_checks_safety_before_execution_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    monkeypatch.setattr(
        retry_handler.code_generator,
        "generate",
        lambda _prompt, model=None, config=None: _script("safe code"),
    )

    def fake_check(code: str, config: AppConfig | None = None) -> SafetyResult:
        events.append(f"safety:{code}")
        return SafetyResult(is_safe=True)

    def fake_execute(
        code: str,
        input_path: Path,
        output_path: Path,
        config: AppConfig | None = None,
    ) -> ExecutionResult:
        events.append(f"execute:{code}")
        return _success()

    monkeypatch.setattr(retry_handler.safety_checker, "check", fake_check)
    monkeypatch.setattr(retry_handler.execution_backend, "execute", fake_execute)

    result = retry_handler.run(_prompt(), tmp_path / "input.csv", tmp_path / "out.csv")

    assert result.success is True
    assert events == ["safety:safe code", "execute:safe code"]


def test_run_many_generates_checks_safety_then_executes_validated_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    generated_calls: list[tuple[PromptPayload, str | None]] = []
    executed_inputs: list[list[InputFileSpec]] = []

    def fake_generate(
        prompt: PromptPayload,
        model: str | None = None,
        config: AppConfig | None = None,
    ) -> GeneratedScript:
        events.append("generate")
        generated_calls.append((prompt, model))
        return _script("safe multi code")

    def fake_check(code: str, config: AppConfig | None = None) -> SafetyResult:
        events.append(f"safety:{code}")
        return SafetyResult(is_safe=True)

    def fake_execute(
        code: str,
        input_path: Path | list[InputFileSpec],
        output_path: Path,
        config: AppConfig | None = None,
    ) -> ExecutionResult:
        events.append(f"execute:{code}")
        assert isinstance(input_path, list)
        executed_inputs.append(input_path)
        return _success()

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)
    monkeypatch.setattr(retry_handler.safety_checker, "check", fake_check)
    monkeypatch.setattr(retry_handler.execution_backend, "execute", fake_execute)

    result = retry_handler.run_many(
        _prompt(),
        [
            InputFileSpec(name=" orders ", path=tmp_path / "orders.csv"),
            InputFileSpec(name="\tproducts\n", path=tmp_path / "products.csv"),
        ],
        tmp_path / "out.csv",
    )

    assert result.success is True
    assert events == ["generate", "safety:safe multi code", "execute:safe multi code"]
    assert len(generated_calls) == 1
    assert [input_spec.name for input_spec in executed_inputs[0]] == [
        "orders",
        "products",
    ]
    assert [input_spec.path for input_spec in executed_inputs[0]] == [
        tmp_path / "orders.csv",
        tmp_path / "products.csv",
    ]


def test_run_many_does_not_retry_safety_violations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generate_calls = 0
    execute_calls = 0

    def fake_generate(
        prompt: PromptPayload,
        model: str | None = None,
        config: AppConfig | None = None,
    ) -> GeneratedScript:
        nonlocal generate_calls
        generate_calls += 1
        return _script("import os")

    def fake_execute(
        code: str,
        input_path: Path | list[InputFileSpec],
        output_path: Path,
        config: AppConfig | None = None,
    ) -> ExecutionResult:
        nonlocal execute_calls
        execute_calls += 1
        return _success()

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code, config=None: SafetyResult(
            is_safe=False,
            violations=["Blocked unsafe import: os"],
        ),
    )
    monkeypatch.setattr(retry_handler.execution_backend, "execute", fake_execute)

    result = retry_handler.run_many(
        _prompt(),
        _input_specs(tmp_path),
        tmp_path / "out.csv",
    )

    assert result.success is False
    assert "Safety violation" in result.stderr
    assert "Blocked unsafe import: os" in result.stderr
    assert generate_calls == 1
    assert execute_calls == 0


def test_run_many_treats_ast_invalid_safety_result_as_failure_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execute_calls = 0

    def fake_execute(
        code: str,
        input_path: Path | list[InputFileSpec],
        output_path: Path,
        config: AppConfig | None = None,
    ) -> ExecutionResult:
        nonlocal execute_calls
        execute_calls += 1
        return _success()

    monkeypatch.setattr(
        retry_handler.code_generator,
        "generate",
        lambda _prompt, model=None, config=None: _script("x ="),
    )
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code, config=None: SafetyResult(
            is_safe=True,
            ast_valid=False,
            violations=["Syntax error"],
        ),
    )
    monkeypatch.setattr(retry_handler.execution_backend, "execute", fake_execute)

    result = retry_handler.run_many(
        _prompt(),
        _input_specs(tmp_path),
        tmp_path / "out.csv",
    )

    assert result.success is False
    assert "Safety violation" in result.stderr
    assert "Syntax error" in result.stderr
    assert execute_calls == 0


def test_run_many_retries_stderr_failure_then_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated_calls: list[tuple[PromptPayload, str | None]] = []
    executed_codes: list[str] = []

    def fake_generate(
        prompt: PromptPayload,
        model: str | None = None,
        config: AppConfig | None = None,
    ) -> GeneratedScript:
        generated_calls.append((prompt, model))
        return _script(f"code v{len(generated_calls)}")

    def fake_execute(
        code: str,
        input_path: Path | list[InputFileSpec],
        output_path: Path,
        config: AppConfig | None = None,
    ) -> ExecutionResult:
        executed_codes.append(code)
        if len(executed_codes) == 1:
            return _failure("Traceback (most recent call last):\nValueError: bad")
        return _success()

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code, config=None: SafetyResult(is_safe=True),
    )
    monkeypatch.setattr(retry_handler.execution_backend, "execute", fake_execute)

    result = retry_handler.run_many(
        _prompt(),
        _input_specs(tmp_path),
        tmp_path / "out.csv",
    )

    assert result.success is True
    assert executed_codes == ["code v1", "code v2"]
    assert len(generated_calls) == 2
    retry_prompt = generated_calls[1][0]
    assert retry_prompt.system_prompt == "system prompt"
    assert "original user prompt" in retry_prompt.user_prompt
    assert "ValueError: bad" in retry_prompt.user_prompt
    assert "code v1" in retry_prompt.user_prompt


@pytest.mark.parametrize(
    "inputs, expected_error",
    [
        ([], "At least one input file is required"),
        (
            [InputFileSpec(name="Orders", path=Path("orders.csv"))],
            "Invalid logical input name",
        ),
        (
            [InputFileSpec(name="customer-id", path=Path("customers.csv"))],
            "Invalid logical input name",
        ),
        (
            [InputFileSpec(name="customer id", path=Path("customers.csv"))],
            "Invalid logical input name",
        ),
        (
            [InputFileSpec(name="1_orders", path=Path("orders.csv"))],
            "Invalid logical input name",
        ),
        (
            [InputFileSpec(name="", path=Path("orders.csv"))],
            "Invalid logical input name",
        ),
        (
            [
                InputFileSpec(name="orders", path=Path("orders.csv")),
                InputFileSpec(name=" orders ", path=Path("other_orders.csv")),
            ],
            "Duplicate logical input name",
        ),
    ],
)
def test_run_many_validation_failures_return_without_generation_or_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    inputs: list[InputFileSpec],
    expected_error: str,
) -> None:
    calls = {"generate": 0, "safety": 0, "execute": 0}

    def fake_generate(
        prompt: PromptPayload,
        model: str | None = None,
        config: AppConfig | None = None,
    ) -> GeneratedScript:
        calls["generate"] += 1
        return _script("code")

    def fake_check(code: str, config: AppConfig | None = None) -> SafetyResult:
        calls["safety"] += 1
        return SafetyResult(is_safe=True)

    def fake_execute(
        code: str,
        input_path: Path | list[InputFileSpec],
        output_path: Path,
        config: AppConfig | None = None,
    ) -> ExecutionResult:
        calls["execute"] += 1
        return _success()

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)
    monkeypatch.setattr(retry_handler.safety_checker, "check", fake_check)
    monkeypatch.setattr(retry_handler.execution_backend, "execute", fake_execute)

    result = retry_handler.run_many(_prompt(), inputs, tmp_path / "out.csv")

    assert result.success is False
    assert result.exit_code == 1
    assert expected_error in result.stderr
    assert calls == {"generate": 0, "safety": 0, "execute": 0}


@pytest.mark.parametrize("category,retry", [
    ("sandbox_failure", True), ("output_validation", True),
    ("timeout", False), ("capture_limit", False), ("output_empty", False),
    ("output_limit", False), ("output_commit", False), ("workspace_failure", False),
    ("input_validation", False), ("backend_unavailable", False),
    ("safety_violation", False), ("provider_authentication", False),
])
def test_execution_retry_depends_only_on_category(category, retry):
    result = ExecutionResult(False, stderr="The diagnostic wording changed", exit_code=1, error_category=category)
    assert retry_handler._should_retry_execution(result) is retry


@pytest.mark.parametrize("message", [
    "ValueError: upstream lookup timed out",
    "ValueError: column contains Output exceeds size limit",
    "ValueError: field named Output already exists",
    "ValueError: literal Input validation: is part of this field",
    "Output is empty",
])
def test_script_message_cannot_override_repairable_category(message):
    result = ExecutionResult(False, stderr=message, exit_code=1, error_category="sandbox_failure")
    assert retry_handler._should_retry_execution(result)


@pytest.mark.parametrize("category,message,expected", [
    ("safety_violation", "Static checks rejected this candidate", 2),
    ("sandbox_failure", "Safety violation: a user-provided field name", 3),
])
def test_cli_exit_status_uses_category(category, message, expected):
    result = ExecutionResult(False, stderr=message, exit_code=1, error_category=category)
    assert cli._execution_status(result) == expected


@pytest.mark.parametrize("docker", [False, True])
@pytest.mark.parametrize("kind,category", [
    ("script", "sandbox_failure"), ("validation", "input_validation"),
    ("timeout", "timeout"), ("capture", "capture_limit"),
])
def test_backend_sets_categories_at_the_process_boundary(tmp_path, monkeypatch, docker, kind, category):
    stderr = "ValueError: lookup timed out" if kind == "script" else "ValueError: Input validation: missing pid"
    outcome = subprocess.CompletedProcess(["fixture"], 1, "", stderr)
    if kind == "timeout":
        outcome = subprocess.TimeoutExpired(["fixture"], 1)
    elif kind == "capture":
        outcome = CaptureLimitExceeded("fixture", "fixture")
    runner = _docker_runtime if docker else sandbox_executor
    monkeypatch.setattr(runner, "run_process", Mock(side_effect=outcome) if isinstance(outcome, Exception) else Mock(return_value=outcome))
    monkeypatch.setattr(_docker_runtime, "_remove_container", lambda name: None)
    run = _docker_runtime.run if docker else sandbox_executor._run_script
    result = run(tmp_path, AppConfig(sandbox_backend="docker" if docker else "subprocess"), time.monotonic())
    assert not result.success
    assert result.error_category == category
