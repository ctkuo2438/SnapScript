from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import chardet
import pandas as pd
from openpyxl import load_workbook

from snapscript.config import AppConfig
from snapscript.core.models import ColumnInfo, SchemaReport

# create a SnapScript-specific error hierarchy for schema inspection issues
# inherit from python build-in Exception
class SchemaInspectionError(Exception):
    """Base error for schema inspection failures."""


class MissingInputFileError(SchemaInspectionError):
    """Raised when the requested input file does not exist."""


class UnsupportedFileTypeError(SchemaInspectionError):
    """Raised when the input file extension is not supported."""


class UnreadableFileError(SchemaInspectionError):
    """Raised when a supported file cannot be read."""


class InputFileTooLargeError(SchemaInspectionError):
    """Raised when the input file exceeds configured size limits."""


SUPPORTED_EXTENSIONS = frozenset({".csv", ".xlsx", ".xls"})


def inspect(path: Path, sheet: str | None = None) -> SchemaReport:
    config = AppConfig()
    input_path = Path(path)
    _validate_path(input_path, config)

    suffix = input_path.suffix.lower()
    try:
        if suffix == ".csv":
            return _inspect_csv(input_path, config)
        return _inspect_excel(input_path, sheet, config)
    except SchemaInspectionError:
        raise
    except Exception as exc:
        raise UnreadableFileError(f"Could not read file: {input_path}") from exc


def _validate_path(path: Path, config: AppConfig) -> None:
    if not path.exists():
        raise MissingInputFileError(f"File not found: {path}")
    if not path.is_file():
        raise UnreadableFileError(f"Input path is not a file: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(f"Unsupported file type: {path.suffix}")

    file_size = path.stat().st_size
    if file_size > config.max_input_file_size_bytes:
        raise InputFileTooLargeError(
            f"File too large: {file_size} bytes exceeds "
            f"{config.max_input_file_size_bytes} bytes"
        )


def _inspect_csv(path: Path, config: AppConfig) -> SchemaReport:
    encoding = _detect_encoding(path)
    sample = pd.read_csv(path, nrows=config.schema_inspect_rows, encoding=encoding)
    sample = _truncate_columns(sample, config)

    return SchemaReport(
        filename=path.name,
        file_type="csv",
        row_count=_count_csv_rows(path, encoding),
        file_size_bytes=path.stat().st_size,
        columns=_build_columns(sample),
        sample_rows=_sample_rows(sample, config),
        encoding=encoding,
        sheet_names=[],
    )


def _inspect_excel(
    path: Path, sheet: str | None, config: AppConfig
) -> SchemaReport:
    excel_file = pd.ExcelFile(path)
    sheet_names = list(excel_file.sheet_names)
    selected_sheet = sheet or sheet_names[0]
    if selected_sheet not in sheet_names:
        raise UnreadableFileError(f"Sheet not found: {selected_sheet}")

    sample = pd.read_excel(
        excel_file,
        sheet_name=selected_sheet,
        nrows=config.schema_inspect_rows,
    )
    sample = _truncate_columns(sample, config)

    return SchemaReport(
        filename=path.name,
        file_type=path.suffix.lower().lstrip("."),
        row_count=_count_excel_rows(path, selected_sheet, sample),
        file_size_bytes=path.stat().st_size,
        columns=_build_columns(sample),
        sample_rows=_sample_rows(sample, config),
        encoding="utf-8",
        sheet_names=sheet_names,
    )


def _detect_encoding(path: Path) -> str:
    with path.open("rb") as file:
        raw = file.read(64 * 1024)

    detected = chardet.detect(raw)
    encoding = detected.get("encoding")
    return encoding or "utf-8"


def _count_csv_rows(path: Path, encoding: str) -> int:
    with path.open("r", encoding=encoding, newline="") as file:
        reader = csv.reader(file)
        try:
            next(reader)
        except StopIteration:
            return 0
        return sum(1 for _ in reader)


def _count_excel_rows(path: Path, sheet: str, sample: pd.DataFrame) -> int:
    if path.suffix.lower() != ".xlsx":
        return len(sample)

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook[sheet]
        return max(worksheet.max_row - 1, 0)
    finally:
        workbook.close()


def _truncate_columns(df: pd.DataFrame, config: AppConfig) -> pd.DataFrame:
    truncated = df.copy()
    truncated.columns = [
        str(column)[: config.max_column_name_chars] for column in truncated.columns
    ]
    return truncated


def _build_columns(df: pd.DataFrame) -> list[ColumnInfo]:
    columns: list[ColumnInfo] = []
    for column_name in df.columns:
        series = df[column_name]
        non_null = series.dropna()
        columns.append(
            ColumnInfo(
                name=str(column_name),
                dtype=str(series.dtype),
                null_count=int(series.isna().sum()),
                unique_count=int(series.nunique(dropna=True)),
                sample_values=_sample_values(non_null),
            )
        )
    return columns


def _sample_values(series: pd.Series[Any]) -> list[str]:
    values: list[str] = []
    for value in series.drop_duplicates().head(5).tolist():
        values.append(str(value))
    return values


def _sample_rows(df: pd.DataFrame, config: AppConfig) -> list[dict[str, object]]:
    records = df.head(config.schema_sample_rows).where(pd.notna(df), None).to_dict(
        orient="records"
    )
    return [dict(record) for record in records]
