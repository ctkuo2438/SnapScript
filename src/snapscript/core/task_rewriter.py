"""
Provider-backed natural-language task rewriting.
"""

from __future__ import annotations

from pathlib import Path
import re

from snapscript.core import provider
from snapscript.core._prompt_data import serialize_prompt_data
from snapscript.config import AppConfig
from snapscript.core.models import (
    MultiFileSchemaReport,
    ErrorCategory,
    RewrittenTask,
    SchemaReport,
    TaskAdvice,
    PromptPayload,
    ProviderReply,
)


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "task_rewrite.txt"
CODE_PATTERNS = (
    r"```",
    r"(?m)^\s*import\s+[\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*\s*(?:;|$)",
    r"(?m)^\s*from\s+[\w.]+\s+import\s+(?:\w+|\*)",
    r"(?m)^\s*(?:async\s+)?def\s+\w+\s*\(",
    r"(?m)^\s*class\s+\w+(?:\([^)]*\))?\s*:",
    r"\b(?:pd|pandas)\.\w+\s*\(",
    r"\bread_csv\s*\(",
    r"\bread_excel\s*\(",
    r"\bto_csv\s*\(",
    r"\bto_excel\s*\(",
    r"\bINPUT_PATHS?\b",
    r"\bOUTPUT_PATH\b",
)
_PATH_START = r"(?:~[\w.-]*[/\\]|/(?!/)|[A-Za-z]:[/\\]|\\\\)"
REAL_PATH_PATTERN = re.compile(
    rf'''(?<![\w/\\<])(?:["']{_PATH_START}[^"'\r\n]+["']|{_PATH_START}[^\s,;'"<>]+)'''
)
FILE_NAME_PATTERN = re.compile(
    r"\b[^\s/\\]+\.(?:csv|xlsx)\b",
    flags=re.IGNORECASE,
)

class TaskRewriteError(Exception):
    """Safe failure with a category and optional provider metadata."""

    def __init__(self, message: str, *, category: ErrorCategory = "provider_failure") -> None:
        super().__init__(message)
        self.category = category
        self.api_calls = []


def rewrite_task(
    original_task: str,
    schema: SchemaReport | MultiFileSchemaReport,
    advice: TaskAdvice | None = None,
    model: str | None = None,
    config: AppConfig | None = None,
) -> RewrittenTask:
    config = config if config is not None else AppConfig()
    system_prompt = _load_rewrite_prompt()
    user_prompt = _build_rewrite_user_prompt(original_task, schema, advice)

    try:
        response = _call_provider(
            system_prompt,
            user_prompt,
            model,
            config=config,
        )
    except TaskRewriteError:
        raise
    except Exception:
        raise TaskRewriteError("Task rewrite provider call failed") from None

    rewritten = _strip_rewrite_output(response.text)
    try:
        _validate_rewritten_task(rewritten)
    except TaskRewriteError as exc:
        exc.api_calls = [response.metrics]
        raise
    return RewrittenTask(
        original_task=original_task,
        rewritten_task=rewritten,
        provider=response.metrics.provider,
        model=response.metrics.model,
        api_call=response.metrics,
    )


def _load_rewrite_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def _build_rewrite_user_prompt(
    original_task: str,
    schema: SchemaReport | MultiFileSchemaReport,
    advice: TaskAdvice | None,
) -> str:
    parts = [
        "<schema>",
        _schema_summary_for_rewrite(schema),
        "</schema>",
    ]
    if advice is not None:
        parts.extend(
            [
                "<task_advice>",
                _advice_summary_for_rewrite(advice),
                "</task_advice>",
            ]
        )
    parts.extend(
        [
            "<original_task>",
            serialize_prompt_data(_redact_paths_and_filenames(original_task.strip())),
            "</original_task>",
            "Rewrite the original task. Return only the rewritten task text.",
        ]
    )
    return "\n".join(parts)


def _schema_summary_for_rewrite(schema: SchemaReport | MultiFileSchemaReport) -> str:
    if isinstance(schema, MultiFileSchemaReport):
        data = {"files": [
            {"logical_name": file.name, **_schema_metadata(file.schema)}
            for file in schema.files
        ]}
    elif isinstance(schema, SchemaReport):
        data = _schema_metadata(schema)
    else:
        raise TypeError("schema must be SchemaReport or MultiFileSchemaReport")
    return serialize_prompt_data(data)


def _schema_metadata(schema: SchemaReport) -> dict[str, object]:
    return {
        "file_type": schema.file_type, "row_count": schema.row_count,
        "selected_sheet": schema.selected_sheet,
        "columns": [
            {"name": column.name, "dtype": column.dtype, "null_count": column.null_count}
            for column in schema.columns
        ],
    }


def _advice_summary_for_rewrite(advice: TaskAdvice) -> str:
    return serialize_prompt_data({
        "quality": advice.quality,
        "missing_details": [_redact_paths_and_filenames(detail) for detail in advice.missing_details],
        "suggestions": [_redact_paths_and_filenames(suggestion) for suggestion in advice.suggestions],
        "suggested_task": _redact_paths_and_filenames(advice.suggested_task) if advice.suggested_task else None,
    })


def _strip_rewrite_output(text: str) -> str:
    stripped = text.strip()
    fenced = re.fullmatch(
        r"```(?:text|markdown)?\s*(.*?)```",
        stripped,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced is not None:
        stripped = fenced.group(1).strip()
    stripped = re.sub(
        r"^\s*(?:rewritten\s+task|task)\s*:\s*",
        "",
        stripped,
        flags=re.IGNORECASE,
    ).strip()
    if len(stripped) >= 2 and stripped[0] in "\"'" and stripped[-1] == stripped[0]:
        return stripped[1:-1].strip()
    return stripped


def _validate_rewritten_task(text: str) -> None:
    if not text.strip():
        raise TaskRewriteError("Rewritten task is empty", category="rewrite_validation")
    if _looks_like_code(text):
        raise TaskRewriteError("Rewritten task must be natural language", category="rewrite_validation")
    if REAL_PATH_PATTERN.search(text) or FILE_NAME_PATTERN.search(text):
        raise TaskRewriteError("Rewritten task must not include real file paths", category="rewrite_validation")


def _looks_like_code(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in CODE_PATTERNS)


def _call_provider(
    system_prompt: str, user_prompt: str, model: str | None, config: AppConfig,
) -> ProviderReply:
    try:
        return provider.call(PromptPayload(system_prompt, user_prompt), model or config.default_model, config)
    except provider.CodeGenerationError as exc:
        message = str(exc) if exc.category == "input_validation" else "Task rewrite provider call failed"
        error = TaskRewriteError(message, category=exc.category)
        error.api_calls = exc.api_calls
        raise error from None


def _redact_paths_and_filenames(text: str) -> str:
    redacted = REAL_PATH_PATTERN.sub("[path]", text)
    return FILE_NAME_PATTERN.sub("[file]", redacted)
