from pathlib import Path

import pytest

from snapscript.core.models import (
    ColumnInfo,
    ExecutionResult,
    GeneratedScript,
    InputFileSpec,
    MultiFileSchemaReport,
    NamedSchemaReport,
    PromptPayload,
    SafetyResult,
    SchemaReport,
)
from snapscript.interfaces import cli


def _schema() -> SchemaReport:
    return SchemaReport(
        filename="orders.csv",
        file_type="csv",
        row_count=3,
        file_size_bytes=64,
        columns=[
            ColumnInfo(name="order_id", dtype="int64"),
            ColumnInfo(name="amount", dtype="float64"),
        ],
    )


def _multi_schema() -> MultiFileSchemaReport:
    return MultiFileSchemaReport(
        files=[
            NamedSchemaReport(name="orders", schema=_schema()),
            NamedSchemaReport(
                name="products",
                schema=SchemaReport(
                    filename="products.csv",
                    file_type="csv",
                    row_count=2,
                    file_size_bytes=64,
                    columns=[
                        ColumnInfo(name="pid", dtype="object"),
                        ColumnInfo(name="product_name", dtype="object"),
                    ],
                ),
            ),
        ]
    )


def _payload() -> PromptPayload:
    return PromptPayload(system_prompt="system", user_prompt="user")


def _script() -> GeneratedScript:
    return GeneratedScript(
        code="print('ok')",
        raw_response="print('ok')",
        model="test-model",
        input_tokens=10,
        output_tokens=5,
    )


def _patch_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
    execution: ExecutionResult | None = None,
    safety: SafetyResult | None = None,
) -> None:
    monkeypatch.setattr(
        cli.schema_inspector,
        "inspect",
        lambda path, sheet=None: calls.append(f"inspect:{sheet}") or _schema(),
    )
    monkeypatch.setattr(
        cli.prompt_builder,
        "build",
        lambda task, schema: calls.append(f"build:{task}") or _payload(),
    )
    monkeypatch.setattr(
        cli.code_generator,
        "generate",
        lambda prompt: calls.append("generate") or _script(),
    )
    monkeypatch.setattr(
        cli.safety_checker,
        "check",
        lambda code: calls.append("safety")
        or (safety if safety is not None else SafetyResult(is_safe=True)),
    )
    monkeypatch.setattr(
        cli.retry_handler,
        "run",
        lambda prompt, input_path, output_path: calls.append("retry")
        or (
            execution
            if execution is not None
            else ExecutionResult(success=True, stdout="wrote output", exit_code=0)
        ),
    )


def test_help_output_lists_phase_1_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "snapscript" in output
    assert "--file" in output
    assert "--output" in output
    assert "NAME=PATH" in output
    assert "two-file" in output
    assert "--dry-run" in output
    assert "--show-code" in output


def test_validates_input_before_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        cli.code_generator,
        "generate",
        lambda prompt: calls.append("generate") or _script(),
    )

    status = cli.main(
        [
            "filter rows",
            "--file",
            str(tmp_path / "missing.csv"),
            "--output",
            str(tmp_path / "out.csv"),
            "--yes",
        ]
    )

    assert status == 1
    assert calls == []
    assert "Input file not found" in capsys.readouterr().err


def test_rejects_unsupported_extension_before_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "input.txt"
    input_path.write_text("x\n")
    calls: list[str] = []
    monkeypatch.setattr(
        cli.code_generator,
        "generate",
        lambda prompt: calls.append("generate") or _script(),
    )

    status = cli.main(
        [
            "filter rows",
            "--file",
            str(input_path),
            "--output",
            str(tmp_path / "out.csv"),
            "--yes",
        ]
    )

    assert status == 1
    assert calls == []
    assert "Unsupported input file type" in capsys.readouterr().err


def test_dry_run_generates_and_checks_but_does_not_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "orders.csv"
    input_path.write_text("order_id,amount\n1,10\n")
    calls: list[str] = []
    _patch_pipeline(monkeypatch, calls)

    status = cli.main(
        [
            "filter rows",
            "--file",
            str(input_path),
            "--output",
            str(tmp_path / "out.csv"),
            "--sheet",
            "Orders",
            "--dry-run",
        ]
    )

    output = capsys.readouterr().out
    assert status == 0
    assert calls == ["inspect:Orders", "build:filter rows", "generate", "safety"]
    assert "Schema summary" in output
    assert "test-model" in output
    assert "Safety check passed" in output
    assert "Dry run complete" in output


def test_yes_executes_without_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "orders.csv"
    output_path = tmp_path / "out.csv"
    input_path.write_text("order_id,amount\n1,10\n")
    calls: list[str] = []
    _patch_pipeline(monkeypatch, calls)

    status = cli.main(
        [
            "filter rows",
            "--file",
            str(input_path),
            "--output",
            str(output_path),
            "--yes",
        ]
    )

    output = capsys.readouterr().out
    assert status == 0
    assert calls == ["inspect:None", "build:filter rows", "retry"]
    assert "Execution succeeded" in output


def test_two_named_files_call_multi_file_core_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    orders_path = tmp_path / "orders.csv"
    products_path = tmp_path / "products.csv"
    output_path = tmp_path / "joined.csv"
    orders_path.write_text("order_id,pid\n1,p1\n")
    products_path.write_text("pid,product_name\np1,Keyboard\n")
    calls: list[str] = []
    seen_specs: list[list[InputFileSpec]] = []

    monkeypatch.setattr(
        cli.schema_inspector,
        "inspect_many",
        lambda specs: calls.append("inspect_many")
        or seen_specs.append(specs)
        or _multi_schema(),
    )
    monkeypatch.setattr(
        cli.prompt_builder,
        "build_many",
        lambda task, multi_schema: calls.append(f"build_many:{task}") or _payload(),
    )
    monkeypatch.setattr(
        cli.retry_handler,
        "run_many",
        lambda prompt, specs, output: calls.append("run_many")
        or seen_specs.append(specs)
        or ExecutionResult(success=True, stdout="joined output", exit_code=0),
    )
    monkeypatch.setattr(
        cli.schema_inspector,
        "inspect",
        lambda path, sheet=None: pytest.fail("single-file inspect should not run"),
    )
    monkeypatch.setattr(
        cli.prompt_builder,
        "build",
        lambda task, schema: pytest.fail("single-file prompt builder should not run"),
    )
    monkeypatch.setattr(
        cli.retry_handler,
        "run",
        lambda prompt, input_path, output_path: pytest.fail("single-file retry should not run"),
    )

    status = cli.main(
        [
            "merge orders and products",
            "--file",
            f"orders={orders_path}",
            "--file",
            f"products={products_path}",
            "--output",
            str(output_path),
            "--yes",
        ]
    )

    assert status == 0
    assert calls == ["inspect_many", "build_many:merge orders and products", "run_many"]
    assert [[spec.name for spec in specs] for specs in seen_specs] == [
        ["orders", "products"],
        ["orders", "products"],
    ]
    assert [[spec.path for spec in specs] for specs in seen_specs] == [
        [orders_path, products_path],
        [orders_path, products_path],
    ]
    assert "Execution succeeded" in capsys.readouterr().out


def test_rejects_sheet_in_multi_file_mode_before_core_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    orders_path = tmp_path / "orders.csv"
    products_path = tmp_path / "products.csv"
    orders_path.write_text("order_id,pid\n1,p1\n")
    products_path.write_text("pid,product_name\np1,Keyboard\n")
    calls: list[str] = []

    monkeypatch.setattr(
        cli.schema_inspector,
        "inspect_many",
        lambda specs: calls.append("inspect_many") or _multi_schema(),
    )
    monkeypatch.setattr(
        cli.prompt_builder,
        "build_many",
        lambda task, multi_schema: calls.append("build_many") or _payload(),
    )
    monkeypatch.setattr(
        cli.retry_handler,
        "run_many",
        lambda prompt, specs, output: calls.append("run_many")
        or ExecutionResult(success=True, exit_code=0),
    )

    status = cli.main(
        [
            "merge orders and products",
            "--file",
            f"orders={orders_path}",
            "--file",
            f"products={products_path}",
            "--output",
            str(tmp_path / "joined.csv"),
            "--sheet",
            "Orders",
            "--yes",
        ]
    )

    assert status == 1
    assert calls == []
    assert "--sheet is only supported in single-file mode for now." in capsys.readouterr().err


def test_asks_for_confirmation_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "orders.csv"
    input_path.write_text("order_id,amount\n1,10\n")
    calls: list[str] = []
    _patch_pipeline(monkeypatch, calls)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    status = cli.main(
        [
            "filter rows",
            "--file",
            str(input_path),
            "--output",
            str(tmp_path / "out.csv"),
        ]
    )

    assert status == 1
    assert calls == ["inspect:None", "build:filter rows"]


def test_show_code_prints_generated_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "orders.csv"
    input_path.write_text("order_id,amount\n1,10\n")
    calls: list[str] = []
    _patch_pipeline(monkeypatch, calls)

    status = cli.main(
        [
            "filter rows",
            "--file",
            str(input_path),
            "--output",
            str(tmp_path / "out.csv"),
            "--dry-run",
            "--show-code",
        ]
    )

    assert status == 0
    assert "print('ok')" in capsys.readouterr().out


def test_api_key_is_not_printed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "orders.csv"
    input_path.write_text("order_id,amount\n1,10\n")
    calls: list[str] = []
    _patch_pipeline(monkeypatch, calls)

    status = cli.main(
        [
            "filter rows",
            "--file",
            str(input_path),
            "--output",
            str(tmp_path / "out.csv"),
            "--dry-run",
            "--api-key",
            "secret-api-key",
            "--verbose",
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "secret-api-key" not in captured.out
    assert "secret-api-key" not in captured.err
    assert "Verbose mode enabled" in captured.out


def test_api_key_is_redacted_from_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "orders.csv"
    input_path.write_text("order_id,amount\n1,10\n")
    calls: list[str] = []
    _patch_pipeline(monkeypatch, calls)

    def fail_retry(
        prompt: PromptPayload, input_path: Path, output_path: Path
    ) -> ExecutionResult:
        raise RuntimeError("provider rejected secret-api-key")

    monkeypatch.setattr(cli.retry_handler, "run", fail_retry)

    status = cli.main(
        [
            "filter rows",
            "--file",
            str(input_path),
            "--output",
            str(tmp_path / "out.csv"),
            "--yes",
            "--api-key",
            "secret-api-key",
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "secret-api-key" not in captured.out
    assert "secret-api-key" not in captured.err
    assert "[redacted]" in captured.err


def test_safety_failure_stops_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "orders.csv"
    input_path.write_text("order_id,amount\n1,10\n")
    calls: list[str] = []
    _patch_pipeline(
        monkeypatch,
        calls,
        execution=ExecutionResult(
            success=False,
            stderr="Safety violation: Blocked unsafe import: os",
            exit_code=1,
        ),
    )

    status = cli.main(
        [
            "filter rows",
            "--file",
            str(input_path),
            "--output",
            str(tmp_path / "out.csv"),
            "--yes",
        ]
    )

    assert status == 2
    assert calls == ["inspect:None", "build:filter rows", "retry"]
    assert "Blocked unsafe import" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("file_args", "expected_error"),
    [
        (["orders.csv", "products.csv"], "must use NAME=PATH"),
        (["orders=orders.csv", "products.csv"], "must use NAME=PATH"),
        (["orders=orders.csv", "products=products.csv", "extra=extra.csv"], "at most two"),
        (["Orders=orders.csv", "products=products.csv"], "Invalid logical input name"),
        (["orders=orders.csv", "orders=other.csv"], "Duplicate logical input name"),
        (["=orders.csv", "products=products.csv"], "empty name"),
        (["orders=", "products=products.csv"], "empty path"),
    ],
)
def test_rejects_invalid_multi_file_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    file_args: list[str],
    expected_error: str,
) -> None:
    calls: list[str] = []
    for filename in ("orders.csv", "products.csv", "other.csv", "extra.csv"):
        (tmp_path / filename).write_text("x\n")
    monkeypatch.setattr(
        cli.schema_inspector,
        "inspect_many",
        lambda specs: calls.append("inspect_many") or _multi_schema(),
    )
    argv = ["merge files"]
    for file_arg in file_args:
        name, separator, path = file_arg.partition("=")
        if separator and path:
            argv.extend(["--file", f"{name}={tmp_path / path}"])
        else:
            argv.extend(["--file", file_arg])
    argv.extend(["--output", str(tmp_path / "out.csv"), "--yes"])

    status = cli.main(argv)

    assert status == 1
    assert calls == []
    assert expected_error in capsys.readouterr().err


def test_core_modules_do_not_import_ui_dependencies() -> None:
    for path in Path("src/snapscript/core").glob("*.py"):
        source = path.read_text()
        assert "argparse" not in source
        assert "rich" not in source
        assert "streamlit" not in source
        assert "sys.argv" not in source


def test_cli_does_not_call_provider_sdk_or_sandbox_directly() -> None:
    source = Path("src/snapscript/interfaces/cli.py").read_text(encoding="utf-8")

    assert "import anthropic" not in source.lower()
    assert "from anthropic" not in source.lower()
    assert "import openai" not in source.lower()
    assert "from openai" not in source.lower()
    assert "sandbox_executor" not in source
    assert "docker_sandbox_executor" not in source
