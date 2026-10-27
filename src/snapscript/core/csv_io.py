"""Shared bounded encoding detection and strict CSV preview reading."""
import codecs
from io import BytesIO
from pathlib import Path

import chardet
import pandas as pd


def detect_encoding(source: Path | bytes) -> str:
    if isinstance(source, bytes):
        sample = source[:65536]
    else:
        with source.open("rb") as stream:
            sample = stream.read(65536)
    for marks, encoding in (
        ((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE), "utf-32"),
        ((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE), "utf-16"),
        ((codecs.BOM_UTF8,), "utf-8-sig"),
    ):
        if sample.startswith(marks):
            return encoding
    return chardet.detect(sample).get("encoding") or "utf-8"


def read_csv_preview(source: Path | bytes, nrows: int) -> pd.DataFrame:
    buffer = BytesIO(source) if isinstance(source, bytes) else source
    try:
        return pd.read_csv(buffer, nrows=nrows, encoding="utf-8-sig")
    except UnicodeDecodeError:
        encoding = detect_encoding(source)
        if isinstance(buffer, BytesIO):
            buffer.seek(0)
        return pd.read_csv(buffer, nrows=nrows, encoding=encoding)
