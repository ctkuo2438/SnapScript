'''
CLI wrapper
'''

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from snapscript.config import AppConfig
from snapscript.interfaces.errors import format_exception_error, safe_error_text
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
    InputValidationError,
    MultiFileSchemaReport,
    PromptPayload,
    SafetyResult,
    SchemaReport,
)


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
        "--model",
        help="Provider model name to use for this run.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show additional run metadata.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = sys.argv[1:] if argv is None else argv
    if any(arg == "--api-key" or arg.startswith("--api-key=") for arg in arguments):
        parser.error("--api-key was removed. Set ANTHROPIC_API_KEY or use uv run --env-file .env.")
    args = parser.parse_args(arguments)
    console = Console()
    error_console = Console(stderr=True)

    output_path = Path(args.output)

    input_mode = _parse_file_args(args.file)
    if isinstance(input_mode, str):
        error_console.print(input_mode, markup=False)
        return 1

    try:
        config = AppConfig()

        if args.verbose:
            console.print("Verbose mode enabled")

        prompt = _prepare_prompt(input_mode, args, config, console)
        if not args.dry_run:
            if not args.yes and not _confirm_execution():
                console.print("Execution cancelled.")
                return 1

            run = retry_handler.run if isinstance(input_mode, Path) else retry_handler.run_many
            result = run(prompt, input_mode, output_path, model=args.model, config=config)
            _show_execution_result(console, error_console, result)
            return _execution_status(result)

        return _dry_run(prompt, args, config, console, error_console)
    except Exception as exc:
        error_console.print(format_exception_error(exc), markup=False)
        return 1


def _prepare_prompt(
    inputs: Path | list[InputFileSpec], args: argparse.Namespace, config: AppConfig, console: Console,
) -> PromptPayload:
    if isinstance(inputs, Path):
        schema = schema_inspector.inspect(inputs, sheet=args.sheet, config=config)
        _show_schema_summary(console, schema)
        return prompt_builder.build(args.task, schema, config=config)
    if args.sheet:
        raise InputValidationError("--sheet is only supported in single-file mode for now.")
    schema = schema_inspector.inspect_many(inputs, config=config)
    _show_multi_schema_summary(console, schema)
    return prompt_builder.build_many(args.task, schema, config=config)


def _dry_run(
    prompt: PromptPayload, args: argparse.Namespace, config: AppConfig,
    console: Console, error_console: Console,
) -> int:
    generated = code_generator.generate(prompt, model=args.model, config=config)
    _show_generation_metadata(console, generated)
    safety = safety_checker.check(generated.code, config=config)
    _show_safety_result(console, safety)
    if not safety.is_safe or not safety.ast_valid:
        error_console.print("\n".join(safety.violations), markup=False)
        return 2
    if args.show_code:
        _show_generated_code(console, generated.code)
    console.print("Dry run complete; generated code was not executed.")
    return 0


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


def _show_schema_summary(console: Console, schema: SchemaReport) -> None:
    console.print("Schema summary")
    console.print(f"File: {schema.filename} ({schema.file_type})", markup=False)
    console.print(f"Rows: {schema.row_count}")
    console.print(f"Columns: {len(schema.columns)}")
    for column in schema.columns:
        console.print(f"- {column.name}: {column.dtype}", markup=False)


def _show_multi_schema_summary(console: Console, schema: MultiFileSchemaReport) -> None:
    console.print("Schema summary")
    for file_schema in schema.files:
        console.print(f"Input: {file_schema.name}", markup=False)
        _show_schema_summary(console, file_schema.schema)


def _show_generation_metadata(console: Console, generated: GeneratedScript) -> None:
    console.print("Generation metadata")
    console.print(f"Model: {generated.model}", markup=False)
    console.print(f"Input tokens: {generated.input_tokens}")
    console.print(f"Output tokens: {generated.output_tokens}")


def _show_safety_result(console: Console, safety: SafetyResult) -> None:
    if safety.is_safe and safety.ast_valid:
        console.print("Safety check passed")
        return

    console.print("Safety check failed")
    for violation in safety.violations:
        console.print(f"- {violation}", markup=False)


def _show_generated_code(console: Console, code: str) -> None:
    console.print("Generated code")
    # print the original code, don't treat the [] as markup for rich 
    #   since the generated code may contain arbitrary brackets
    console.print(code, markup=False)


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
        console.print(safe_error_text(result.stdout), markup=False)
    if result.stderr:
        error_console.print(safe_error_text(result.stderr), markup=False)
    if result.output_files:
        console.print("Output files:")
        for output_file in result.output_files:
            console.print(f"- {output_file}", markup=False)


def _execution_status(result: ExecutionResult) -> int:
    if result.success:
        return 0
    if result.error_category == "safety_violation":
        return 2
    return 3
