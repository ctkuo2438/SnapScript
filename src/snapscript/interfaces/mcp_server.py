"""Local stdio MCP tools over SnapScript's existing safe core pipeline."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from snapscript.config import AppConfig
from snapscript.core import prompt_builder, retry_handler, schema_inspector
from snapscript.core.audit_logger import redact_secret_values
from snapscript.core.models import InputFileSpec, NamedSchemaReport


MAX_SCHEMA_COLUMNS = 100
MAX_ERROR_CHARS = 1000


def create_server(workspace: Path, config: AppConfig | None = None) -> MCPServer:
    """Bind the two tools to one existing host directory and Docker backend."""
    tools = _Tools(workspace, config)
    server = MCPServer(
        "SnapScript", log_level="WARNING",
        instructions=(
            "Read the user's data-task spec, inspect named CSV/XLSX schemas, "
            "then transform_files and verify the output against the spec. "
            "Paths are relative to the configured workspace. Use one or two "
            "inputs and a new output filename. Transformation requires the "
            "configured Claude provider and Docker; inspection requires neither."
        ),
    )
    server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))(
        tools.inspect_file_schema
    )
    server.tool(annotations=ToolAnnotations(destructiveHint=False, openWorldHint=True))(
        tools.transform_files
    )
    return server


class _Tools:
    """The two tool handlers share one workspace and immutable core config."""

    def __init__(self, workspace: Path, config: AppConfig | None) -> None:
        self.workspace = workspace.resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("Workspace must be an existing directory")
        selected = config if config is not None else AppConfig(
            sandbox_backend="docker", docker_network_disabled=True,
        )
        self.config = replace(
            selected, sandbox_backend="docker", docker_network_disabled=True,
            docker_timeout_seconds=min(selected.docker_timeout_seconds, 30),
        )

    def inspect_file_schema(self, files: dict[str, str]) -> dict[str, Any]:
        """Inspect 1-2 named CSV/XLSX files in the workspace, without cell values.

        files maps logical names (e.g. orders) to workspace-relative paths.
        XLSX uses its first sheet. Dtypes come from a bounded sample; only the
        first 100 columns are returned, with a truncation flag.
        """
        try:
            inputs = _resolve_inputs(files, self.workspace)
            report = schema_inspector.inspect_many(inputs, config=self.config)
            return {"success": True, "files": [_schema_metadata(item) for item in report.files]}
        except Exception as exc:
            raise _tool_error(str(exc)) from None

    def transform_files(
        self, files: dict[str, str], task: str, output_path: str,
    ) -> dict[str, Any]:
        """Transform 1-2 named CSV/XLSX files using Claude, AST checks and Docker.

        task is the natural-language processing requirement. output_path must
        be a new CSV/XLSX filename within the workspace, with an existing parent.
        Sources are preserved; errors do not supply an output. The 30-second
        limit applies to each Docker execution, excluding provider calls/retries.
        """
        try:
            if not task.strip():
                raise ValueError("Task must not be empty")
            inputs = _resolve_inputs(files, self.workspace)
            output = _resolve_output(output_path, self.workspace)
            schema = schema_inspector.inspect_many(inputs, config=self.config)
            prompt = prompt_builder.build_many(task, schema, config=self.config)
            result = retry_handler.run_many(prompt, inputs, output, config=self.config)
            if not result.success:
                raise ValueError(result.stderr or f"Transformation failed (exit code {result.exit_code})")
            return {
                "success": True, "output_path": str(output),
                "file_size_bytes": output.stat().st_size,
                "execution_time_seconds": result.execution_time_seconds,
                "sandbox_backend": "docker",
            }
        except Exception as exc:
            raise _tool_error(str(exc)) from None


def _workspace_path(value: str, workspace: Path) -> Path:
    if not value.strip():
        raise ValueError("File path must not be empty")
    requested = Path(value)
    if ".." in requested.parts:
        raise ValueError("File paths must not contain '..'")
    resolved = (workspace / requested).resolve()
    if not resolved.is_relative_to(workspace):
        raise ValueError("File path is outside the configured workspace")
    return resolved


def _resolve_inputs(files: dict[str, str], workspace: Path) -> list[InputFileSpec]:
    return schema_inspector.validate_input_specs([
        InputFileSpec(name=name, path=_workspace_path(path, workspace))
        for name, path in files.items()
    ])


def _resolve_output(value: str, workspace: Path) -> Path:
    output = _workspace_path(value, workspace)
    if (workspace / value).is_symlink():
        raise ValueError("Output must not be a symlink; choose a new output path")
    if output.suffix.lower() not in schema_inspector.SUPPORTED_EXTENSIONS:
        raise ValueError("Output must be a .csv or .xlsx file")
    if output.exists():
        raise ValueError("Output already exists; choose a new output path")
    if not output.parent.is_dir():
        raise ValueError("Output parent directory must already exist")
    return output


def _schema_metadata(item: NamedSchemaReport) -> dict[str, Any]:
    schema = item.schema
    return {
        "name": item.name, "filename": schema.filename, "file_type": schema.file_type,
        "row_count": schema.row_count, "file_size_bytes": schema.file_size_bytes,
        "encoding": schema.encoding, "sheet_names": schema.sheet_names,
        "column_count": len(schema.columns),
        "columns": [
            {"name": column.name, "dtype": column.dtype}
            for column in schema.columns[:MAX_SCHEMA_COLUMNS]
        ],
        "columns_truncated": len(schema.columns) > MAX_SCHEMA_COLUMNS,
    }


def _tool_error(message: str) -> ToolError:
    if "Traceback (most recent call last):" in message:
        message = message.strip().splitlines()[-1]
    safe_message = redact_secret_values(message.strip() or "SnapScript operation failed")
    return ToolError(safe_message[:MAX_ERROR_CHARS])


def main() -> None:
    parser = argparse.ArgumentParser(description="SnapScript local stdio MCP server")
    parser.add_argument("--workspace", type=Path, required=True, help="Allowed CSV/XLSX directory")
    args = parser.parse_args()
    try:
        server = create_server(args.workspace)
    except (OSError, ValueError) as exc:
        parser.error(str(_tool_error(str(exc))))
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
