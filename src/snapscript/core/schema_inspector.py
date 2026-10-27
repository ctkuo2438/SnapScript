"""Inspect CSV/XLSX schemas and count rows without loading the entire dataset."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import load_workbook

from snapscript.config import AppConfig
from snapscript.core.csv_io import detect_encoding as _detect_encoding
from snapscript.core.models import (
    ColumnInfo,
    ErrorCategory,
    InputFileSpec,
    MultiFileSchemaReport,
    NamedSchemaReport,
    SchemaReport,
)


class SchemaInspectionError(Exception):
    """Base error for schema inspection failures."""
    category: ErrorCategory = "input_validation"

class MissingInputFileError(SchemaInspectionError):
    """Raised when the requested input file does not exist."""

class UnsupportedFileTypeError(SchemaInspectionError):
    """Raised when the input file extension is not supported."""

class UnreadableFileError(SchemaInspectionError):
    """Raised when a supported file cannot be read."""

class InputFileTooLargeError(SchemaInspectionError):
    """Raised when the input file exceeds configured size limits."""

SUPPORTED_EXTENSIONS = frozenset({".csv", ".xlsx"})
LOGICAL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def inspect(path: Path, sheet: str | None = None, config: AppConfig | None = None) -> SchemaReport:
    config = config if config is not None else AppConfig()
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


def inspect_many(
    inputs: list[InputFileSpec],
    config: AppConfig | None = None,
) -> MultiFileSchemaReport:
    config = config if config is not None else AppConfig()
    validated_inputs = validate_input_specs(inputs)
    files = [
        NamedSchemaReport(
            name=input_spec.name,

            schema=inspect(
                input_spec.path,
                sheet=input_spec.sheet,
                config=config,
            ),
        )
        for input_spec in validated_inputs
    ]
    return MultiFileSchemaReport(files=files)


def validate_input_specs(inputs: list[InputFileSpec]) -> list[InputFileSpec]:
    if not inputs:
        raise SchemaInspectionError("At least one input file is required")
    if len(inputs) > 2:
        raise SchemaInspectionError("Phase 4A supports at most two input files")

    seen_names: set[str] = set()
    validated_inputs: list[InputFileSpec] = []
    for input_spec in inputs:
        name = _validate_logical_name(input_spec.name)
        if name in seen_names:
            raise SchemaInspectionError(f"Duplicate logical input name: {name}")
        seen_names.add(name)
        validated_inputs.append(
            InputFileSpec(
                name=name,
                path=Path(input_spec.path),
                sheet=input_spec.sheet,
                display_filename=input_spec.display_filename,
            )
        )
    return validated_inputs


def _validate_logical_name(name: str) -> str:
    trimmed_name = name.strip()
    if not LOGICAL_NAME_PATTERN.fullmatch(trimmed_name):
        raise SchemaInspectionError(f"Invalid logical input name: {name!r}")
    return trimmed_name


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


def _inspect_excel(path: Path, sheet: str | None, config: AppConfig) -> SchemaReport:
    with pd.ExcelFile(path) as excel_file:
        sheet_names = [str(name) for name in excel_file.sheet_names]


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
            row_count=_count_excel_rows(path, selected_sheet),
            file_size_bytes=path.stat().st_size,
            columns=_build_columns(sample),
            sample_rows=_sample_rows(sample, config),
            encoding="utf-8",
            sheet_names=sheet_names,
            selected_sheet=selected_sheet,
        )


def _count_csv_rows(path: Path, encoding: str) -> int:
    with pd.read_csv(
        path, encoding=encoding, usecols=[0], dtype=str,
        keep_default_na=False, chunksize=1000,
    ) as chunks:
        return sum(len(chunk) for chunk in chunks)


def _count_excel_rows(path: Path, sheet: str) -> int:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook[sheet]
        rows = worksheet.max_row
        if rows is None:
            rows = sum(1 for _ in worksheet.iter_rows())
        return max(rows - 1, 0)
    finally:
        workbook.close()


def _truncate_columns(df: pd.DataFrame, config: AppConfig) -> pd.DataFrame:
    truncated = df.copy()

    seen_counts: dict[str, int] = {}
    used_names: set[str] = set()
    column_names: list[str] = []
    for column in truncated.columns:
        base_name = str(column)[: config.max_column_name_chars]
        seen_counts[base_name] = seen_counts.get(base_name, 0) + 1
        if seen_counts[base_name] == 1:
            candidate = base_name
        else:
            candidate = f"{base_name}_{seen_counts[base_name]}"
        while candidate in used_names:
            seen_counts[base_name] += 1
            candidate = f"{base_name}_{seen_counts[base_name]}"
        used_names.add(candidate)
        column_names.append(candidate)
    truncated.columns = column_names
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
