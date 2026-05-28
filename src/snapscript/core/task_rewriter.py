"""
Provider-backed natural-language task rewriting.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from anthropic import Anthropic

from snapscript.config import AppConfig
from snapscript.core.models import (
    MultiFileSchemaReport,
    RewrittenTask,
    SchemaReport,
    TaskAdvice,
)


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "task_rewrite.txt"
CODE_PATTERNS = (
    r"```",
    r"\bimport\s+\w+",
    r"\bfrom\s+\w+\s+import\b",
    r"\bdef\s+\w+\s*\(",
    r"\bclass\s+\w+",
    r"\bpd\.",
    r"\bpandas\b",
    r"\bread_csv\s*\(",
    r"\bread_excel\s*\(",
    r"\bto_csv\s*\(",
    r"\bto_excel\s*\(",
    r"\bINPUT_PATHS?\b",
    r"\bOUTPUT_PATH\b",
)
REAL_PATH_PATTERN = re.compile(
    r"(?:/(?:private/)?(?:tmp|var|Users|home)/[^\s,;]+|[A-Za-z]:\\[^\s,;]+)"
)
FILE_NAME_PATTERN = re.compile(
    r"\b[^\s/\\]+\.(?:csv|xlsx|xls)\b",
    flags=re.IGNORECASE,
)


class TaskRewriteError(Exception):
    """Raised when task rewriting fails safely."""


def rewrite_task(
    original_task: str,
    schema: SchemaReport | MultiFileSchemaReport,
    advice: TaskAdvice | None = None,
    model: str | None = None,
) -> RewrittenTask:
    system_prompt = _load_rewrite_prompt()
    user_prompt = _build_rewrite_user_prompt(original_task, schema, advice)

    try:
        raw_text, provider, selected_model = _call_provider(
            system_prompt,
            user_prompt,
            model,
        )
    except TaskRewriteError:
        raise
    except Exception:
        raise TaskRewriteError("Task rewrite provider call failed") from None

    rewritten = _strip_rewrite_output(raw_text)
    _validate_rewritten_task(rewritten, schema)
    return RewrittenTask(
        original_task=original_task,
        rewritten_task=rewritten,
        provider=provider,
        model=selected_model,
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
            _redact_paths_and_filenames(original_task.strip()),
            "</original_task>",
            "Rewrite the original task. Return only the rewritten task text.",
        ]
    )
    return "\n".join(parts)


def _schema_summary_for_rewrite(
    schema: SchemaReport | MultiFileSchemaReport,
) -> str:
    if isinstance(schema, MultiFileSchemaReport):
        return "\n".join(
            _named_schema_summary(file_schema.name, file_schema.schema)
            for file_schema in schema.files
        )
    if isinstance(schema, SchemaReport):
        return _single_schema_summary(schema)
    raise TypeError("schema must be SchemaReport or MultiFileSchemaReport")


def _single_schema_summary(schema: SchemaReport) -> str:
    lines = [
        "<file>",
        f"file_type: {schema.file_type}",
        f"row_count: {schema.row_count}",
        "columns:",
    ]
    lines.extend(_column_lines(schema))
    lines.append("</file>")
    return "\n".join(lines)


def _named_schema_summary(name: str, schema: SchemaReport) -> str:
    lines = [
        f'<file name="{name}">',
        f"file_type: {schema.file_type}",
        f"row_count: {schema.row_count}",
        "columns:",
    ]
    lines.extend(_column_lines(schema))
    lines.append("</file>")
    return "\n".join(lines)


def _column_lines(schema: SchemaReport) -> list[str]:
    return [
        f"- {column.name}: {column.dtype}, null_count={column.null_count}"
        for column in schema.columns
    ]


def _advice_summary_for_rewrite(advice: TaskAdvice) -> str:
    lines = [f"quality: {advice.quality}"]
    if advice.missing_details:
        lines.append("missing_details:")
        lines.extend(
            f"- {_redact_paths_and_filenames(detail)}"
            for detail in advice.missing_details
        )
    if advice.suggestions:
        lines.append("suggestions:")
        lines.extend(
            f"- {_redact_paths_and_filenames(suggestion)}"
            for suggestion in advice.suggestions
        )
    if advice.suggested_task:
        lines.append(
            f"suggested_task: {_redact_paths_and_filenames(advice.suggested_task)}"
        )
    return "\n".join(lines)


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
    return stripped.strip("\"'")


def _validate_rewritten_task(
    text: str,
    schema: SchemaReport | MultiFileSchemaReport,
) -> None:
    if not text.strip():
        raise TaskRewriteError("Rewritten task is empty")
    if _looks_like_code(text):
        raise TaskRewriteError("Rewritten task must be natural language")
    if REAL_PATH_PATTERN.search(text) or FILE_NAME_PATTERN.search(text):
        raise TaskRewriteError("Rewritten task must not include real file paths")
    unknown_column = _unknown_referenced_column(text, schema)
    if unknown_column is not None:
        raise TaskRewriteError(f"Rewritten task references unknown column: {unknown_column}")


def _looks_like_code(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in CODE_PATTERNS)


def _unknown_referenced_column(
    text: str,
    schema: SchemaReport | MultiFileSchemaReport,
) -> str | None:
    valid_columns = {column.lower() for column in _schema_columns(schema)}
    file_names = {name.lower() for name in _schema_file_names(schema)}
    for candidate in _candidate_column_references(text):
        normalized = candidate.lower()
        if normalized not in valid_columns and normalized not in file_names:
            return candidate
    return None


def _schema_columns(schema: SchemaReport | MultiFileSchemaReport) -> list[str]:
    if isinstance(schema, MultiFileSchemaReport):
        return [
            column.name
            for file_schema in schema.files
            for column in file_schema.schema.columns
        ]
    return [column.name for column in schema.columns]


def _schema_file_names(schema: SchemaReport | MultiFileSchemaReport) -> list[str]:
    if isinstance(schema, MultiFileSchemaReport):
        return [file_schema.name for file_schema in schema.files]
    return []


def _candidate_column_references(text: str) -> list[str]:
    patterns = (
        r"\bwhere\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\busing\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\bon\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\bby\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\bcolumn\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    )
    candidates: list[str] = []
    for pattern in patterns:
        candidates.extend(
            match.group(1) for match in re.finditer(pattern, text, re.IGNORECASE)
        )
    return candidates


def _call_provider(
    system_prompt: str,
    user_prompt: str,
    model: str | None,
) -> tuple[str, str, str]:
    config = AppConfig()
    provider = config.llm_provider.lower()
    selected_model = model or config.default_model
    if provider != "anthropic":
        raise TaskRewriteError(
            f"Unsupported LLM provider: {config.llm_provider}"
        )

    try:
        client = Anthropic()
        response = client.messages.create(
            model=selected_model,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception:
        raise TaskRewriteError("Task rewrite provider call failed") from None

    return _extract_text(response), provider, selected_model


def _redact_paths_and_filenames(text: str) -> str:
    redacted = REAL_PATH_PATTERN.sub("[path]", text)
    return FILE_NAME_PATTERN.sub("[file]", redacted)


def _extract_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts).strip()
