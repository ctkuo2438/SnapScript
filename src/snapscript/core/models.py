'''
for internal data models used across the application, not use for external API models
'''
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ColumnInfo:
    name: str
    dtype: str
    null_count: int = 0
    unique_count: int = 0
    sample_values: list[str] = field(default_factory=list)


@dataclass
class SchemaReport:
    filename: str
    file_type: str
    row_count: int
    file_size_bytes: int
    columns: list[ColumnInfo] = field(default_factory=list)
    sample_rows: list[dict[str, object]] = field(default_factory=list)
    encoding: str = "utf-8"
    sheet_names: list[str] = field(default_factory=list)


@dataclass
class PromptPayload:
    system_prompt: str
    user_prompt: str


@dataclass
class GeneratedScript:
    code: str
    raw_response: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class SafetyResult:
    is_safe: bool
    violations: list[str] = field(default_factory=list)
    ast_valid: bool = True


@dataclass
class ExecutionResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    output_files: list[Path] = field(default_factory=list)
    execution_time_seconds: float = 0.0
    exit_code: int = 0
