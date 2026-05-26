from pathlib import Path

import pandas as pd
import pytest

from snapscript.config import AppConfig
from snapscript.core import schema_inspector
from snapscript.core.models import InputFileSpec, MultiFileSchemaReport, SchemaReport
from snapscript.core.schema_inspector import (
    InputFileTooLargeError,
    MissingInputFileError,
    SchemaInspectionError,
    UnsupportedFileTypeError,
    UnreadableFileError,
)


FIXTURES = Path("tests/fixtures/integration")


def test_inspect_csv_reports_schema_without_ui_dependencies() -> None:
    report = schema_inspector.inspect(FIXTURES / "task_02_orders.csv")

    assert isinstance(report, SchemaReport)
    assert report.filename == "task_02_orders.csv"
    assert report.file_type == "csv"
    assert report.row_count == 500
    assert report.file_size_bytes > 0
    assert report.encoding
    assert report.sheet_names == []
    assert [column.name for column in report.columns] == [
        "order_id",
        "customer",
        "amount",
        "status",
    ]
    assert report.columns[0].dtype.startswith("int")
    assert report.columns[0].null_count == 0
    assert report.columns[0].unique_count == 500
    assert report.columns[0].sample_values[:3] == ["1", "2", "3"]
    assert len(report.sample_rows) == AppConfig().schema_sample_rows
    assert report.sample_rows[0]["customer"] == "bLdoKM"


def test_inspect_excel_reports_sheet_names_and_selected_sheet(tmp_path: Path) -> None:
    workbook = tmp_path / "contacts.xlsx"
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame(
            {
                "name": ["Ada", "Grace", None],
                "score": [10, 20, 30],
            }
        ).to_excel(writer, sheet_name="people", index=False)
        pd.DataFrame({"ignored": [1]}).to_excel(
            writer, sheet_name="other", index=False
        )

    report = schema_inspector.inspect(workbook, sheet="people")

    assert report.filename == "contacts.xlsx"
    assert report.file_type == "xlsx"
    assert report.row_count == 3
    assert report.sheet_names == ["people", "other"]
    assert [column.name for column in report.columns] == ["name", "score"]
    assert report.columns[0].null_count == 1
    assert report.columns[0].unique_count == 2
    assert report.columns[0].sample_values == ["Ada", "Grace"]
    assert report.sample_rows[0] == {"name": "Ada", "score": 10}


def test_inspect_many_with_two_csv_files_returns_named_schema_reports() -> None:
    report = schema_inspector.inspect_many(
        [
            InputFileSpec(name="orders", path=FIXTURES / "task_02_orders.csv"),
            InputFileSpec(name="customers", path=FIXTURES / "task_01_customers.csv"),
        ]
    )

    assert isinstance(report, MultiFileSchemaReport)
    assert [file.name for file in report.files] == ["orders", "customers"]
    assert report.files[0].schema.filename == "task_02_orders.csv"
    assert report.files[1].schema.filename == "task_01_customers.csv"
    assert [column.name for column in report.files[0].schema.columns] == [
        "order_id",
        "customer",
        "amount",
        "status",
    ]


def test_inspect_many_preserves_input_order() -> None:
    report = schema_inspector.inspect_many(
        [
            InputFileSpec(name="customers", path=FIXTURES / "task_01_customers.csv"),
            InputFileSpec(name="orders", path=FIXTURES / "task_02_orders.csv"),
        ]
    )

    assert [file.name for file in report.files] == ["customers", "orders"]
    assert [file.schema.filename for file in report.files] == [
        "task_01_customers.csv",
        "task_02_orders.csv",
    ]


def test_inspect_many_trims_whitespace_before_validation() -> None:
    report = schema_inspector.inspect_many(
        [
            InputFileSpec(name=" orders ", path=FIXTURES / "task_02_orders.csv"),
            InputFileSpec(name="\tcustomers\n", path=FIXTURES / "task_01_customers.csv"),
        ]
    )

    assert [file.name for file in report.files] == ["orders", "customers"]


def test_validate_input_specs_trims_names_preserves_order_and_metadata(
    tmp_path: Path,
) -> None:
    orders_path = tmp_path / "orders.csv"
    products_path = tmp_path / "products.csv"
    inputs = [
        InputFileSpec(
            name=" orders ",
            path=orders_path,
            sheet="orders_sheet",
            display_filename="Uploaded Orders.csv",
        ),
        InputFileSpec(
            name="\tproducts\n",
            path=products_path,
            sheet=None,
            display_filename="Uploaded Products.csv",
        ),
    ]

    validated = schema_inspector.validate_input_specs(inputs)

    assert [input_spec.name for input_spec in validated] == ["orders", "products"]
    assert [input_spec.path for input_spec in validated] == [
        orders_path,
        products_path,
    ]
    assert validated[0].sheet == "orders_sheet"
    assert validated[1].sheet is None
    assert validated[0].display_filename == "Uploaded Orders.csv"
    assert validated[1].display_filename == "Uploaded Products.csv"
    assert validated is not inputs
    assert [input_spec.name for input_spec in inputs] == [" orders ", "\tproducts\n"]


def test_validate_input_specs_rejects_duplicate_names_after_trimming() -> None:
    with pytest.raises(SchemaInspectionError, match="Duplicate logical input name"):
        schema_inspector.validate_input_specs(
            [
                InputFileSpec(name="orders", path=FIXTURES / "task_02_orders.csv"),
                InputFileSpec(name=" orders ", path=FIXTURES / "task_01_customers.csv"),
            ]
        )


@pytest.mark.parametrize(
    "name",
    ["Orders", "customer-id", "customer id", "1_orders", ""],
)
def test_validate_input_specs_rejects_invalid_logical_names(name: str) -> None:
    with pytest.raises(SchemaInspectionError, match="Invalid logical input name"):
        schema_inspector.validate_input_specs(
            [InputFileSpec(name=name, path=FIXTURES / "task_02_orders.csv")]
        )


def test_inspect_many_rejects_duplicate_logical_names() -> None:
    with pytest.raises(SchemaInspectionError, match="Duplicate logical input name"):
        schema_inspector.inspect_many(
            [
                InputFileSpec(name="orders", path=FIXTURES / "task_02_orders.csv"),
                InputFileSpec(name=" orders ", path=FIXTURES / "task_01_customers.csv"),
            ]
        )


@pytest.mark.parametrize(
    "name",
    ["Orders", "customer-id", "customer id", "1_orders", ""],
)
def test_inspect_many_rejects_invalid_logical_names(name: str) -> None:
    with pytest.raises(SchemaInspectionError, match="Invalid logical input name"):
        schema_inspector.inspect_many(
            [InputFileSpec(name=name, path=FIXTURES / "task_02_orders.csv")]
        )


def test_inspect_many_does_not_silently_normalize_case() -> None:
    with pytest.raises(SchemaInspectionError, match="Invalid logical input name"):
        schema_inspector.inspect_many(
            [InputFileSpec(name="Orders", path=FIXTURES / "task_02_orders.csv")]
        )


def test_inspect_many_rejects_empty_input_list() -> None:
    with pytest.raises(SchemaInspectionError, match="At least one input file"):
        schema_inspector.inspect_many([])


def test_inspect_many_raises_for_unsupported_extension(tmp_path: Path) -> None:
    text_file = tmp_path / "input.txt"
    text_file.write_text("name\nAda\n")

    with pytest.raises(UnsupportedFileTypeError):
        schema_inspector.inspect_many([InputFileSpec(name="input", path=text_file)])


def test_inspect_many_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(MissingInputFileError):
        schema_inspector.inspect_many(
            [InputFileSpec(name="missing", path=tmp_path / "missing.csv")]
        )


def test_inspect_many_supports_excel_paths(tmp_path: Path) -> None:
    workbook = tmp_path / "contacts.xlsx"
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame({"name": ["Ada", "Grace"], "score": [10, 20]}).to_excel(
            writer,
            sheet_name="people",
            index=False,
        )

    report = schema_inspector.inspect_many(
        [InputFileSpec(name="contacts", path=workbook, sheet="people")]
    )

    assert report.files[0].name == "contacts"
    assert report.files[0].schema.filename == "contacts.xlsx"
    assert report.files[0].schema.sheet_names == ["people"]


def test_inspect_truncates_column_names_for_prompt_safety(tmp_path: Path) -> None:
    config = AppConfig()
    long_column = "x" * (config.max_column_name_chars + 25)
    csv_path = tmp_path / "long_column.csv"
    pd.DataFrame({long_column: [1]}).to_csv(csv_path, index=False)

    report = schema_inspector.inspect(csv_path)

    assert report.columns[0].name == "x" * config.max_column_name_chars
    assert list(report.sample_rows[0]) == ["x" * config.max_column_name_chars]


def test_inspect_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(MissingInputFileError):
        schema_inspector.inspect(tmp_path / "missing.csv")


def test_inspect_raises_for_unsupported_extension(tmp_path: Path) -> None:
    text_file = tmp_path / "input.txt"
    text_file.write_text("name\nAda\n")

    with pytest.raises(UnsupportedFileTypeError):
        schema_inspector.inspect(text_file)


def test_inspect_raises_for_unreadable_supported_file(tmp_path: Path) -> None:
    workbook = tmp_path / "broken.xlsx"
    workbook.write_text("not a real workbook")

    with pytest.raises(UnreadableFileError):
        schema_inspector.inspect(workbook)


def test_inspect_raises_for_too_large_file(monkeypatch: pytest.MonkeyPatch) -> None:
    input_file = FIXTURES / "task_02_orders.csv"

    monkeypatch.setattr(
        schema_inspector,
        "AppConfig",
        lambda: AppConfig(max_input_file_size_bytes=input_file.stat().st_size - 1),
    )

    with pytest.raises(InputFileTooLargeError):
        schema_inspector.inspect(input_file)


def test_schema_inspector_core_has_no_ui_dependencies() -> None:
    source = Path("src/snapscript/core/schema_inspector.py").read_text()

    assert "argparse" not in source
    assert "rich" not in source
    assert "streamlit" not in source
    assert "sys.argv" not in source
