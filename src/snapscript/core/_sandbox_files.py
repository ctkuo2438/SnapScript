"""Shared destination guards and output validation for both sandbox backends."""

from pathlib import Path

import pandas as pd

from snapscript.core.models import InputFileSpec


def validate_destination(inputs: Path | list[InputFileSpec], output_path: Path) -> str | None:
    specs = inputs if isinstance(inputs, list) else [InputFileSpec(name="input", path=inputs)]
    output = Path(output_path)
    for spec in specs:
        source = Path(spec.path)
        if output.resolve() == source.resolve() or (
            output.exists() and source.exists() and output.samefile(source)
        ):
            return f"Output would overwrite input '{spec.name}'; choose a different output path"
    return None


def validate_output(output_path: Path) -> str | None:
    if output_path.is_symlink():
        return "Output must not be a symlink"
    if not output_path.exists():
        return "Output file was not created"
    if not output_path.is_file():
        return "Output is not a regular file"
    if output_path.stat().st_size == 0:
        return "Output is empty"
    try:
        if output_path.suffix.lower() == ".xlsx":
            preview = pd.read_excel(output_path, nrows=1)
        else:
            preview = pd.read_csv(output_path, nrows=1)
    except Exception as exc:
        return f"Output unreadable: {exc}"
    return "Output is empty" if preview.empty else None
