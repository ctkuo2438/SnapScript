from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from snapscript.interfaces import web


def test_normalize_task_text_strips_whitespace() -> None:
    assert web.normalize_task_text("  Keep large orders. \n") == (
        "Keep large orders."
    )

def test_validate_task_text_accepts_nonblank_text() -> None:
    assert web.validate_task_text("  Keep large orders. ") == (
        "Keep large orders."
    )

@pytest.mark.parametrize("task_text", ["", "   ", "\n\t"])
def test_validate_task_text_rejects_blank_text(task_text: str) -> None:
    with pytest.raises(ValueError, match="Task description is required"):
        web.validate_task_text(task_text)

def test_can_generate_rejects_missing_upload() -> None:
    can_run, message = web.can_generate(
        {
            "uploaded_file_bytes": None,
            "uploaded_file_suffix": None,
            "task_text": "Keep large orders.",
            "run_count": 0,
        }
    )

    assert can_run is False
    assert message == "Upload a CSV or Excel file before generating."

def test_can_generate_rejects_blank_task_text() -> None:
    can_run, message = web.can_generate(
        {
            "uploaded_file_bytes": b"order_id,total\n1,10\n",
            "uploaded_file_suffix": ".csv",
            "task_text": "   ",
            "run_count": 0,
        }
    )

    assert can_run is False
    assert message == "Task description is required."

def test_can_generate_rejects_run_limit() -> None:
    can_run, message = web.can_generate(
        {
            "uploaded_file_bytes": b"order_id,total\n1,10\n",
            "uploaded_file_suffix": ".csv",
            "task_text": "Keep large orders.",
            "run_count": web.MAX_RUNS_PER_SESSION,
        }
    )

    assert can_run is False
    assert message == "Run limit reached for this session."

def test_can_generate_accepts_valid_upload_and_task_text() -> None:
    can_run, message = web.can_generate(
        {
            "uploaded_file_bytes": b"order_id,total\n1,10\n",
            "uploaded_file_suffix": ".csv",
            "task_text": "Keep large orders.",
            "run_count": 0,
        }
    )

    assert can_run is True
    assert message is None

@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("orders.csv", ".csv"),
        ("orders.xlsx", ".xlsx"),
        ("orders.xls", ".xls"),
        ("ORDERS.CSV", ".csv"),
    ],
)
def test_validate_upload_suffix_accepts_supported_suffixes(
    file_name: str,
    expected: str,
) -> None:
    assert web.validate_upload_suffix(file_name) == expected

def test_validate_upload_suffix_rejects_unsupported_suffix() -> None:
    with pytest.raises(ValueError, match="Unsupported file type"):
        web.validate_upload_suffix("orders.txt")

def test_validate_upload_size_rejects_large_upload() -> None:
    with pytest.raises(ValueError, match="10 MB"):
        web.validate_upload_size(web.MAX_UPLOAD_BYTES + 1)

def test_store_uploaded_file_sets_name_suffix_and_bytes() -> None:
    state: dict[str, object] = {"error_message": "old error"}
    file_bytes = b"order_id,total\n1,10\n"

    web.store_uploaded_file(state, "Orders.CSV", file_bytes)

    assert state["uploaded_file_name"] == "Orders.CSV"
    assert state["uploaded_file_suffix"] == ".csv"
    assert state["uploaded_file_bytes"] == file_bytes
    assert state["error_message"] is None

def test_store_uploaded_file_rejects_invalid_data_before_storing() -> None:
    state: dict[str, object] = {
        "uploaded_file_name": "previous.csv",
        "uploaded_file_suffix": ".csv",
        "uploaded_file_bytes": b"previous",
        "error_message": None,
    }

    with pytest.raises(ValueError, match="Unsupported file type"):
        web.store_uploaded_file(state, "orders.txt", b"not,csv\n")

    assert state["uploaded_file_name"] is None
    assert state["uploaded_file_suffix"] is None
    assert state["uploaded_file_bytes"] is None
    assert state["error_message"] == "Unsupported file type: .txt"

def test_write_upload_to_temp_input_uses_internal_filename(
    tmp_path: Path,
) -> None:
    file_bytes = b"order_id,total\n1,10\n"

    input_path = web.write_upload_to_temp_input(
        tmp_path,
        file_bytes,
        ".csv",
    )

    assert input_path == tmp_path / "input.csv"
    assert input_path.read_bytes() == file_bytes
    assert input_path.resolve().parent == tmp_path.resolve()

@pytest.mark.parametrize(
    ("uploaded_file_name", "suffix", "expected"),
    [
        ("orders.csv", ".csv", "orders_snapscript_output.csv"),
        ("Orders.XLSX", ".xlsx", "Orders_snapscript_output.xlsx"),
        ("../../secret.csv", ".csv", "secret_snapscript_output.csv"),
        (None, ".csv", "snapscript_output.csv"),
        ("...csv", ".csv", "snapscript_output.csv"),
    ],
)
def test_derive_output_file_name_uses_safe_upload_stem(
    uploaded_file_name: str | None,
    suffix: str,
    expected: str,
) -> None:
    assert web.derive_output_file_name(uploaded_file_name, suffix) == expected

def test_load_output_preview_reads_csv_bytes() -> None:
    preview = web.load_output_preview(b"order_id,amount\n1,1500\n", ".csv")

    assert list(preview.columns) == ["order_id", "amount"]
    assert preview.to_dict(orient="records") == [
        {"order_id": 1, "amount": 1500}
    ]

def test_load_output_preview_limits_csv_rows() -> None:
    rows = ["row_id"] + [str(index) for index in range(150)]
    preview = web.load_output_preview(
        "\n".join(rows).encode("utf-8"),
        ".csv",
    )

    assert len(preview) == 100
    assert preview["row_id"].iloc[-1] == 99

def test_load_output_preview_reads_excel_bytes() -> None:
    buffer = BytesIO()
    pd.DataFrame({"order_id": [1], "amount": [1500]}).to_excel(
        buffer,
        index=False,
    )

    preview = web.load_output_preview(buffer.getvalue(), ".xlsx")

    assert preview.to_dict(orient="records") == [
        {"order_id": 1, "amount": 1500}
    ]

def test_path_like_upload_name_does_not_affect_temp_filename(
    tmp_path: Path,
) -> None:
    state: dict[str, object] = {}
    file_bytes = b"order_id,total\n1,10\n"
    web.store_uploaded_file(state, "../../secret.csv", file_bytes)

    input_path = web.write_upload_to_temp_input(
        tmp_path,
        bytes(state["uploaded_file_bytes"]),
        str(state["uploaded_file_suffix"]),
    )

    assert input_path == tmp_path / "input.csv"
    assert input_path.read_bytes() == file_bytes
