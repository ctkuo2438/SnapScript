'''
CLI wrapper
'''

from __future__ import annotations

import argparse
import os
from pathlib import Path

from rich.console import Console

from snapscript.core import (
    code_generator,
    prompt_builder,
    retry_handler,
    safety_checker,
    schema_inspector,
)
from snapscript.core.models import (
    ExecutionResult,
    GeneratedScript,
    InputFileSpec,
    MultiFileSchemaReport,
    SafetyResult,
    SchemaReport,
)


SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="snapscript",
        description="Generate and run local Python scripts for CSV/Excel tasks.",
    )
    parser.add_argument("task", help="Natural-language data processing task.")
    parser.add_argument(
        "--file",
        "-f",
        required=True,
        action="append",
        help=(
            "Input CSV or Excel file. Use --file PATH for single-file mode, "
            "or repeat --file NAME=PATH exactly twice for two-file mode."
        ),
        metavar="PATH|NAME=PATH",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output CSV or Excel file.",
    )
    parser.add_argument(
        "--sheet",
        "-s",
        help="Excel sheet name to inspect.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect, generate, and safety-check without executing.",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip execution confirmation.",
    )
    parser.add_argument(
        "--show-code",
        action="store_true",
        help="Print generated code after safety checking.",
    )
    parser.add_argument(
        "--api-key",
        help="Provider API key for this run.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show additional run metadata.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console()
    error_console = Console(stderr=True)

    output_path = Path(args.output)

    input_mode = _parse_file_args(args.file)
    if isinstance(input_mode, str):
        error_console.print(input_mode)
        return 1

    previous_api_key = os.environ.get("ANTHROPIC_API_KEY")
    if args.api_key:
        os.environ["ANTHROPIC_API_KEY"] = args.api_key

    try:
        if args.verbose:
            console.print("Verbose mode enabled")

        if isinstance(input_mode, Path):
            validation_error = _validate_input(input_mode)
            if validation_error is not None:
                error_console.print(validation_error)
                return 1

            schema = schema_inspector.inspect(input_mode, sheet=args.sheet)
            _show_schema_summary(console, schema)
            prompt = prompt_builder.build(args.task, schema)
            run_result = lambda: retry_handler.run(prompt, input_mode, output_path)
        else:
            if args.sheet:
                error_console.print("--sheet is only supported in single-file mode for now.")
                return 1

            validation_error = _validate_multi_inputs(input_mode)
            if validation_error is not None:
                error_console.print(validation_error)
                return 1

            schema = schema_inspector.inspect_many(input_mode)
            _show_multi_schema_summary(console, schema)
            prompt = prompt_builder.build_many(args.task, schema)
            run_result = lambda: retry_handler.run_many(prompt, input_mode, output_path)

        if not args.dry_run:
            if not args.yes and not _confirm_execution():
                console.print("Execution cancelled.")
                return 1

            result = run_result()
            _show_execution_result(console, error_console, result)
            return _execution_status(result)

        generated = code_generator.generate(prompt)
        _show_generation_metadata(console, generated)

        safety = safety_checker.check(generated.code)
        _show_safety_result(console, safety)
        if not safety.is_safe:
            error_console.print("\n".join(safety.violations))
            return 2

        if args.show_code:
            _show_generated_code(console, generated.code)

        console.print("Dry run complete; generated code was not executed.")
        return 0
    except Exception as exc:
        error_console.print(_format_exception(exc, args.api_key), markup=False)
        return 1
    finally:
        _restore_api_key(previous_api_key, bool(args.api_key))


def _parse_file_args(file_args: list[str]) -> Path | list[InputFileSpec] | str:
    if len(file_args) == 1:
        return Path(file_args[0])
    if len(file_args) > 2:
        return "Phase 4A supports at most two --file arguments."
    return _parse_multi_file_args(file_args)


def _parse_multi_file_args(file_args: list[str]) -> list[InputFileSpec] | str:
    input_specs: list[InputFileSpec] = []
    for file_arg in file_args:
        if "=" not in file_arg:
            return "Multi-file mode must use NAME=PATH for each --file value."
        name, path_text = file_arg.split("=", 1)
        if not name.strip():
            return "Multi-file --file value has empty name."
        if not path_text.strip():
            return "Multi-file --file value has empty path."
        input_specs.append(InputFileSpec(name=name, path=Path(path_text)))

    try:
        return schema_inspector.validate_input_specs(input_specs)
    except schema_inspector.SchemaInspectionError as exc:
        return str(exc)


def _validate_multi_inputs(input_specs: list[InputFileSpec]) -> str | None:
    for input_spec in input_specs:
        validation_error = _validate_input(input_spec.path)
        if validation_error is not None:
            return validation_error
    return None


def _validate_input(path: Path) -> str | None:
    if not path.exists():
        return f"Input file not found: {path}"
    if not path.is_file():
        return f"Input path is not a file: {path}"
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return f"Unsupported input file type: {path.suffix}"
    return None


def _show_schema_summary(console: Console, schema: SchemaReport) -> None:
    console.print("Schema summary")
    console.print(f"File: {schema.filename} ({schema.file_type})")
    console.print(f"Rows: {schema.row_count}")
    console.print(f"Columns: {len(schema.columns)}")
    for column in schema.columns:
        console.print(f"- {column.name}: {column.dtype}")


def _show_multi_schema_summary(console: Console, schema: MultiFileSchemaReport) -> None:
    console.print("Schema summary")
    for file_schema in schema.files:
        console.print(f"Input: {file_schema.name}")
        _show_schema_summary(console, file_schema.schema)


def _show_generation_metadata(console: Console, generated: GeneratedScript) -> None:
    console.print("Generation metadata")
    console.print(f"Model: {generated.model}")
    console.print(f"Input tokens: {generated.input_tokens}")
    console.print(f"Output tokens: {generated.output_tokens}")


def _show_safety_result(console: Console, safety: SafetyResult) -> None:
    if safety.is_safe:
        console.print("Safety check passed")
        return

    console.print("Safety check failed")
    for violation in safety.violations:
        console.print(f"- {violation}")


def _show_generated_code(console: Console, code: str) -> None:
    console.print("Generated code")
    console.print(code)


def _confirm_execution() -> bool:
    answer = input("Execute generated code? [y/N]: ")
    return answer.strip().lower() in {"y", "yes"}


def _show_execution_result(
    console: Console, error_console: Console, result: ExecutionResult
) -> None:
    if result.success:
        console.print("Execution succeeded")
    else:
        error_console.print("Execution failed")

    if result.stdout:
        console.print(result.stdout.rstrip())
    if result.stderr:
        error_console.print(result.stderr.rstrip())
    if result.output_files:
        console.print("Output files:")
        for output_file in result.output_files:
            console.print(f"- {output_file}")


def _execution_status(result: ExecutionResult) -> int:
    if result.success:
        return 0
    if result.stderr.startswith("Safety violation:"):
        return 2
    return 3


def _restore_api_key(previous_api_key: str | None, was_overridden: bool) -> None:
    if not was_overridden:
        return
    if previous_api_key is None:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    else:
        os.environ["ANTHROPIC_API_KEY"] = previous_api_key


def _format_exception(exc: Exception, api_key: str | None) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if api_key:
        message = message.replace(api_key, "[redacted]")
    return message
