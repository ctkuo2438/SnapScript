---
name: snapscript-module-conventions
description: |
  Use when creating or modifying Python modules under src/snapscript/.
  Triggers: writing core/*, interfaces/*, models.py; adding dataclasses;
  imports across module boundaries; deciding whether code goes in core
  or interface. Do NOT use for tests or external scripts.
---

# SnapScript module conventions

## Layout (src/snapscript/)

    src/snapscript/
    ├── __init__.py
    ├── core/
    │   ├── schema_inspector.py
    │   ├── prompt_builder.py
    │   ├── code_generator.py
    │   ├── safety_checker.py
    │   ├── sandbox_executor.py
    │   ├── retry_handler.py
    │   └── models.py            ← all dataclasses live here
    ├── interfaces/
    │   ├── cli.py               ← Phase 1
    │   └── web.py               ← Phase 2
    ├── prompts/
    │   ├── system.txt           ← THE product (per TODOS prompt iteration)
    │   └── retry.txt
    └── config.py

main.py at repo root is the package entry point. Run via:

    uv run python main.py

## Core principle: interface-agnostic core

Modules under src/snapscript/core/ MUST NOT import:
- streamlit (web UI)
- argparse or click (CLI)
- rich (CLI pretty printing)

Allowed in core/anything.py:

    import pandas as pd
    import anthropic
    from snapscript.core.models import SchemaReport

WRONG in core/anything.py:

    import streamlit as st       # couples core to UI framework
    import argparse                # couples core to CLI
    from rich import print         # couples core to CLI rendering

Phase 3 plans Tauri/FastAPI. A pure core means a new interface = a new file
in interfaces/, with no core changes needed.

## Dataclasses (single source of truth)

src/snapscript/core/models.py holds ALL dataclasses. Other modules import
them, never redefine.

Per SDS section 3 plus TODOS additions:
- SchemaReport — schema_inspector returns this
- ColumnInfo — nested in SchemaReport
- GeneratedScript — code_generator returns this
- SafetyResult — safety_checker returns this
- ExecutionResult — sandbox_executor returns this

Frozen vs mutable:

    @dataclass(frozen=True)
    class AppConfig: ...           # config = frozen

    @dataclass
    class ExecutionResult: ...     # results = mutable (default)

When extending a dataclass, add NEW fields at the END with defaults:

    @dataclass
    class SchemaReport:
        filename: str
        row_count: int
        columns: list[ColumnInfo]
        sample_rows: list[dict]
        file_size_bytes: int
        encoding: str
        sheet_names: list[str]
        # NEW field added later — must have a default
        detected_delimiter: str = ","

## Function signatures

- Type hints on ALL function signatures — no exceptions
- Use pathlib.Path for path arguments inside core (not str)
- Use the | union syntax (Python 3.10+), not Optional[X] or Union[X, Y]
- Dataclass for return types with more than 2 fields; tuple OK for 2 or fewer

Good:

    def inspect(path: Path) -> SchemaReport: ...

    def parse_columns(df: pd.DataFrame) -> list[ColumnInfo]: ...

Bad:

    def inspect(path):                       # no type hints
    def inspect(path: str) -> dict: ...      # str for path, dict for return

## Error handling boundary

Core layer raises exceptions. Interface layer catches and formats them.

In core/schema_inspector.py:

    def inspect(path: Path) -> SchemaReport:
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if file_size > AppConfig.max_input_file_size_bytes:
            raise ValueError(f"File too large: {file_size}")
        ...

In interfaces/cli.py:

    try:
        report = schema_inspector.inspect(args.file)
    except FileNotFoundError as e:
        rich.print(f"[red]Cannot read file:[/red] {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        rich.print(f"[red]{e}[/red]", file=sys.stderr)
        sys.exit(2)

Map exceptions to error categories per SDS section 8.1.

## Public vs private

Public API = function names a sibling module imports. Helpers stay private
(prefix with underscore):

    # core/schema_inspector.py
    def inspect(path: Path) -> SchemaReport:           # public
        return _build_report(_read_sample(path))

    def _read_sample(path: Path) -> pd.DataFrame:      # private
        ...

    def _detect_encoding(raw_bytes: bytes) -> str:     # private
        ...

## File length

- Module > 300 lines → split it
- Function > 50 lines → split it

If code_generator.py grows past 300 lines, the typical split is:
- code_generator.py — public generate() API
- _code_postprocessor.py — markdown stripping, AST validation
- _api_client.py — anthropic SDK wrapper

## What NOT to add to core

- Print statements or rich UI calls (interface layer's job)
- Reading sys.argv or env vars directly (config.py's job)
- Streamlit st.session_state usage (interface layer)
- Network calls outside the Anthropic SDK (per snapscript-safety-rules)

## Imports inside core

When a core module needs config:

    from snapscript.config import AppConfig    # OK

When a core module needs another core module's models:

    from snapscript.core.models import SchemaReport, ColumnInfo    # OK

When a core module needs another core module's functions:

    from snapscript.core import schema_inspector    # OK, but consider whether
                                                     # this couples them too tightly

If two core modules end up importing each other heavily, that's a sign
they should be merged or a third module should hold the shared logic.
