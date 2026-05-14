from pathlib import Path

import pandas as pd
import pytest

from snapscript.core.models import (
    ExecutionResult,
    GeneratedScript,
    PromptPayload,
    SafetyResult,
)
from snapscript.interfaces import cli


def test_cli_pipeline_filters_orders_without_real_api_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_path = Path("tests/fixtures/integration/task_02_orders.csv")
    output_path = tmp_path / "orders_over_1000.csv"
    generated_code = """
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd

df = pd.read_csv(INPUT_PATH)
out = df[df["amount"] > 1000]
out.to_csv(OUTPUT_PATH, index=False)
"""
    generate_calls: list[PromptPayload] = []
    safety_calls: list[str] = []
    sandbox_calls: list[tuple[str, Path, Path]] = []

    def fake_generate(
        prompt: PromptPayload, model: str | None = None
    ) -> GeneratedScript:
        assert model is None
        generate_calls.append(prompt)
        return GeneratedScript(
            code=generated_code,
            raw_response=generated_code,
            model="mock-model",
            input_tokens=0,
            output_tokens=0,
        )

    original_check = cli.safety_checker.check
    original_execute = cli.sandbox_executor.execute

    def check_spy(code: str) -> SafetyResult:
        safety_calls.append(code)
        return original_check(code)

    def execute_spy(
        code: str, input_path: Path, output_path_arg: Path
    ) -> ExecutionResult:
        sandbox_calls.append((code, input_path, output_path_arg))
        return original_execute(code, input_path, output_path_arg)

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli.code_generator, "generate", fake_generate)
    monkeypatch.setattr(cli.safety_checker, "check", check_spy)
    monkeypatch.setattr(cli.sandbox_executor, "execute", execute_spy)

    status = cli.main(
        [
            "Keep only orders where amount is greater than 1000.",
            "--file",
            str(fixture_path),
            "--output",
            str(output_path),
            "--yes",
        ]
    )

    assert status == 0
    assert len(generate_calls) == 1
    assert safety_calls == [generated_code]
    assert len(sandbox_calls) == 1
    assert sandbox_calls[0] == (generated_code, fixture_path, output_path)
    assert output_path.exists()

    output = pd.read_csv(output_path)
    assert not output.empty
    assert (output["amount"] > 1000).all()
