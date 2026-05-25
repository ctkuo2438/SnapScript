from dataclasses import fields, is_dataclass
from pathlib import Path

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


def test_all_shared_models_are_dataclasses() -> None:
    for model in (
        ColumnInfo,
        SchemaReport,
        InputFileSpec,
        NamedSchemaReport,
        MultiFileSchemaReport,
        PromptPayload,
        GeneratedScript,
        SafetyResult,
        ExecutionResult,
    ):
        assert is_dataclass(model)


def test_schema_models_construct_with_defaults() -> None:
    column = ColumnInfo(name="email", dtype="object")
    report = SchemaReport(
        filename="customers.csv",
        file_type="csv",
        row_count=10,
        file_size_bytes=512,
        columns=[column],
    )

    assert column.null_count == 0
    assert column.unique_count == 0
    assert column.sample_values == []
    assert report.columns == [column]
    assert report.sample_rows == []
    assert report.encoding == "utf-8"
    assert report.sheet_names == []


def test_prompt_payload_keeps_system_and_user_prompts_separate() -> None:
    payload = PromptPayload(
        system_prompt="system instructions",
        user_prompt="<schema>columns</schema>\nTask",
    )

    assert payload.system_prompt == "system instructions"
    assert payload.user_prompt.startswith("<schema>")
    assert [field.name for field in fields(PromptPayload)] == [
        "system_prompt",
        "user_prompt",
    ]


def test_input_file_spec_constructs_with_defaults() -> None:
    spec = InputFileSpec(name="orders", path=Path("orders.csv"))

    assert spec.name == "orders"
    assert spec.path == Path("orders.csv")
    assert spec.sheet is None
    assert spec.display_filename is None


def test_named_and_multi_file_schema_reports_preserve_input_order() -> None:
    orders_schema = SchemaReport(
        filename="orders.csv",
        file_type="csv",
        row_count=1,
        file_size_bytes=10,
    )
    products_schema = SchemaReport(
        filename="products.csv",
        file_type="csv",
        row_count=1,
        file_size_bytes=10,
    )
    orders = NamedSchemaReport(name="orders", schema=orders_schema)
    products = NamedSchemaReport(name="products", schema=products_schema)

    report = MultiFileSchemaReport(files=[orders, products])

    assert orders.name == "orders"
    assert orders.schema is orders_schema
    assert [file.name for file in report.files] == ["orders", "products"]
    assert report.files[1].schema is products_schema


def test_generation_safety_and_execution_models_hold_cli_metadata() -> None:
    generated = GeneratedScript(
        code="print('ok')",
        raw_response="```python\nprint('ok')\n```",
        model="test-model",
        input_tokens=12,
        output_tokens=8,
    )
    safety = SafetyResult(is_safe=False, violations=["Blocked import: os"])
    result = ExecutionResult(
        success=False,
        stdout="",
        stderr="Output unreadable",
        output_files=[Path("output.csv")],
        execution_time_seconds=0.2,
        exit_code=1,
    )

    assert generated.model == "test-model"
    assert safety.ast_valid is True
    assert safety.violations == ["Blocked import: os"]
    assert result.success is False
    assert result.stderr == "Output unreadable"
    assert result.output_files == [Path("output.csv")]


def test_execution_result_success_is_the_only_success_field() -> None:
    field_names = {field.name for field in fields(ExecutionResult)}

    assert "success" in field_names
    assert not ({"is_success", "ok", "passed"} & field_names)


def test_core_models_have_no_ui_dependencies() -> None:
    source = Path("src/snapscript/core/models.py").read_text()

    assert "argparse" not in source
    assert "rich" not in source
    assert "streamlit" not in source
    assert "sys.argv" not in source
