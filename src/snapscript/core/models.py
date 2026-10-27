"""Shared input, generation, execution, and provider metadata."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

AdviceQuality = Literal["good", "needs_detail", "too_vague", "not_assessed"]
ErrorCategory = Literal[
    "input_validation", "safety_violation", "backend_unavailable", "workspace_failure",
    "timeout", "capture_limit", "output_validation", "output_empty", "output_limit",
    "output_commit", "sandbox_failure", "generation_failure", "rewrite_validation",
    "provider_authentication", "provider_permission", "provider_not_found",
    "provider_bad_request", "provider_configuration", "provider_rate_limit",
    "provider_timeout", "provider_failure", "unknown_failure",
]


class InputValidationError(ValueError):
    """An explicitly identified caller-input error, not an arbitrary ValueError."""

    category: ErrorCategory = "input_validation"


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
    selected_sheet: str | None = None


@dataclass
class InputFileSpec:
    name: str
    path: Path
    sheet: str | None = None
    display_filename: str | None = None


@dataclass
class NamedSchemaReport:
    name: str
    schema: SchemaReport


@dataclass
class MultiFileSchemaReport:
    files: list[NamedSchemaReport] = field(default_factory=list)


@dataclass(frozen=True)
class TaskAdvice:
    quality: AdviceQuality
    missing_details: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    suggested_task: str | None = None


@dataclass(frozen=True)
class RewrittenTask:
    original_task: str
    rewritten_task: str
    provider: str
    model: str
    api_call: ProviderCallMetrics | None = None


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
    api_call: ProviderCallMetrics | None = None


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
    api_calls: list[ProviderCallMetrics] = field(default_factory=list)
    error_category: ErrorCategory | None = None


@dataclass(frozen=True)
class ProviderCallMetrics:
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int = 0


@dataclass(frozen=True)
class ProviderReply:
    text: str
    metrics: ProviderCallMetrics
    stop_reason: str | None = None
