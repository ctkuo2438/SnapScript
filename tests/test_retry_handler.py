from pathlib import Path

import pytest

from snapscript.config import AppConfig
from snapscript.core import code_generator, retry_handler
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


def _failure(stderr: str, exit_code: int = 1) -> ExecutionResult:
    return ExecutionResult(success=False, stderr=stderr, exit_code=exit_code)


def _input_specs(tmp_path: Path) -> list[InputFileSpec]:
    return [
        InputFileSpec(name="orders", path=tmp_path / "orders.csv"),
        InputFileSpec(name="products", path=tmp_path / "products.csv"),
    ]


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
        prompt: PromptPayload, model: str | None = None
    ) -> GeneratedScript:
        generated_calls.append((prompt, model))
        return scripts[len(generated_calls) - 1]

    def fake_check(code: str) -> SafetyResult:
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
        prompt: PromptPayload, model: str | None = None
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
        lambda code: SafetyResult(is_safe=True),
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
        prompt: PromptPayload, model: str | None = None
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
        lambda code: SafetyResult(
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
        lambda _prompt, model=None: _script("x ="),
    )
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code: SafetyResult(
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
        prompt: PromptPayload, model: str | None = None
    ) -> GeneratedScript:
        nonlocal generate_calls
        generate_calls += 1
        return _script("while True: pass")

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code: SafetyResult(is_safe=True),
    )
    monkeypatch.setattr(
        retry_handler.execution_backend,
        "execute",
        lambda code, input_path, output_path, config=None: _failure(
            "Execution timed out", -1
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
        prompt: PromptPayload, model: str | None = None
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
        prompt: PromptPayload, model: str | None = None
    ) -> GeneratedScript:
        nonlocal generate_calls
        generate_calls += 1
        return _script(f"code v{generate_calls}")

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code: SafetyResult(is_safe=True),
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
        prompt: PromptPayload, model: str | None = None
    ) -> GeneratedScript:
        models.append(model)
        return _script("code")

    monkeypatch.setattr(retry_handler.code_generator, "generate", fake_generate)
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code: SafetyResult(is_safe=True),
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
        lambda _prompt, model=None: _script("safe code"),
    )

    def fake_check(code: str) -> SafetyResult:
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
        prompt: PromptPayload, model: str | None = None
    ) -> GeneratedScript:
        events.append("generate")
        generated_calls.append((prompt, model))
        return _script("safe multi code")

    def fake_check(code: str) -> SafetyResult:
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
        prompt: PromptPayload, model: str | None = None
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
        lambda code: SafetyResult(
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
        lambda _prompt, model=None: _script("x ="),
    )
    monkeypatch.setattr(
        retry_handler.safety_checker,
        "check",
        lambda code: SafetyResult(
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
        prompt: PromptPayload, model: str | None = None
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
        lambda code: SafetyResult(is_safe=True),
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
        prompt: PromptPayload, model: str | None = None
    ) -> GeneratedScript:
        calls["generate"] += 1
        return _script("code")

    def fake_check(code: str) -> SafetyResult:
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
