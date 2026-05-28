"""
Rule-based task quality advice for CSV/Excel transformation requests.
"""

from __future__ import annotations

import re
from typing import Literal

from snapscript.core.models import MultiFileSchemaReport, SchemaReport, TaskAdvice


AdviceQuality = Literal["good", "needs_detail", "too_vague"]
OPERATION_WORDS = frozenset({
    "aggregate", "combine", "convert", "count", "deduplicate", "dedupe",
    "drop", "fill", "filter", "format", "group", "join", "keep", "merge",
    "process", "remove", "replace", "sort", "top",
})
TARGET_COLUMN_OPERATIONS = frozenset({
    "aggregate", "convert", "count", "drop", "fill", "filter", "format",
    "group", "keep", "remove", "replace", "sort", "top",
})
VAGUE_TASKS = frozenset({"clean this", "fix data", "process file", "make it better"})
MULTI_FILE_COMBINE_WORDS = frozenset({"combine", "merge", "join"})
JOIN_TYPE_WORDS = frozenset({"left", "right", "inner", "outer", "full"})
FILTER_CONDITION_WORDS = frozenset({
    "after", "before", "contains", "equal", "equals", "greater", "less",
    "than", "where",
})
SORT_DIRECTION_WORDS = frozenset({
    "ascending", "descending", "asc", "desc", "highest", "lowest",
})


def advise_task(
    task_text: str,
    schema: SchemaReport | MultiFileSchemaReport,
) -> TaskAdvice:
    normalized = _normalize_text(task_text)

    if not normalized:
        return TaskAdvice(
            quality="too_vague",
            missing_details=["desired operation"],
            suggestions=[
                "Describe the transformation, target columns, and expected output."
            ],
        )

    if isinstance(schema, MultiFileSchemaReport):
        return _advise_multi_file(normalized, schema)
    if isinstance(schema, SchemaReport):
        return _advise_single_file(normalized, schema)

    raise TypeError("schema must be SchemaReport or MultiFileSchemaReport")


def _advise_single_file(
    normalized_task: str,
    schema: SchemaReport,
) -> TaskAdvice:
    words = _word_set(normalized_task)
    missing: list[str] = []
    suggestions: list[str] = []

    if normalized_task in VAGUE_TASKS:
        missing.extend(["desired operation", "target column"])
        suggestions.append(
            "Name the operation and the column or condition it should use."
        )
        return _build_advice("too_vague", missing, suggestions)

    operation_words = words & OPERATION_WORDS
    if not operation_words:
        missing.append("desired operation")
        suggestions.append(
            "Start with an action such as filter, sort, fill, replace, or deduplicate."
        )

    referenced_columns = _referenced_columns(normalized_task, schema)
    if _needs_target_column(operation_words) and not referenced_columns:
        missing.append("target column")
        suggestions.append("Mention the column the transformation should use.")

    if operation_words & {"filter", "keep", "remove", "drop"} and not _has_filter_condition(
        normalized_task,
        words,
    ):
        missing.append("filter condition")
        suggestions.append("Include the condition rows must match.")

    if "sort" in operation_words and not words & SORT_DIRECTION_WORDS:
        missing.append("sort direction")
        suggestions.append("Say whether the sort should be ascending or descending.")

    if operation_words & {"deduplicate", "dedupe"} and not referenced_columns:
        missing.append("deduplication key")
        suggestions.append("Mention the column or columns that identify duplicates.")

    return _build_advice(_quality_for_missing(missing), missing, suggestions)


def _advise_multi_file(
    normalized_task: str,
    schema: MultiFileSchemaReport,
) -> TaskAdvice:
    words = _word_set(normalized_task)
    file_names = [file_schema.name for file_schema in schema.files]
    missing: list[str] = []
    suggestions: list[str] = []

    operation_words = words & OPERATION_WORDS
    if not operation_words:
        missing.append("desired operation")
        suggestions.append(
            "Describe whether the files should be joined, merged, combined, or filtered."
        )

    mentioned_files = [
        file_name
        for file_name in file_names
        if _contains_phrase(normalized_task, file_name)
    ]
    if len(mentioned_files) < min(2, len(file_names)):
        missing.append("logical file names")
        suggestions.append(
            "Refer to the input files by logical name: "
            f"{_format_names(file_names)}."
        )

    if operation_words & MULTI_FILE_COMBINE_WORDS:
        if not _has_join_key(normalized_task, schema):
            missing.append("join key")
            suggestions.append(
                "Name the column to join on, or say if the files should be stacked."
            )

        if not words & JOIN_TYPE_WORDS:
            missing.append("join type")
            suggestions.append(
                "Specify inner, left, right, or outer join behavior."
            )

        if words & {"left", "right", "outer", "full"} and not _has_retention_hint(
            normalized_task,
            file_names,
        ):
            missing.append("which file should retain all rows")
            suggestions.append(
                "State which file should keep all rows when using a left or right join."
            )

    suggested_task = None
    if missing and file_names:
        suggested_task = (
            f"Describe how {_format_names(file_names)} should be transformed, "
            "including the operation, key columns, row retention, and output columns."
        )

    return _build_advice(
        _quality_for_missing(missing),
        missing,
        suggestions,
        suggested_task=suggested_task,
    )


def _build_advice(
    quality: AdviceQuality,
    missing: list[str],
    suggestions: list[str],
    suggested_task: str | None = None,
) -> TaskAdvice:
    unique_missing = _dedupe_preserving_order(missing)
    unique_suggestions = _dedupe_preserving_order(suggestions)
    return TaskAdvice(
        quality=quality,
        missing_details=unique_missing,
        suggestions=unique_suggestions,
        suggested_task=suggested_task,
    )


def _quality_for_missing(missing: list[str]) -> AdviceQuality:
    if not missing:
        return "good"
    if "desired operation" in missing:
        return "too_vague"
    return "needs_detail"


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _word_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text))


def _referenced_columns(
    normalized_task: str,
    schema: SchemaReport,
) -> list[str]:
    return [
        column.name
        for column in schema.columns
        if _contains_phrase(normalized_task, column.name)
    ]


def _needs_target_column(operation_words: set[str]) -> bool:
    return bool(operation_words & TARGET_COLUMN_OPERATIONS)


def _has_filter_condition(
    normalized_task: str,
    words: set[str],
) -> bool:
    return bool(
        words & FILTER_CONDITION_WORDS
        or re.search(r"(?:>=|<=|==|!=|>|<|=)\s*\S+", normalized_task)
        or re.search(r"\b\d+(?:\.\d+)?\b", normalized_task)
    )


def _has_join_key(
    normalized_task: str,
    schema: MultiFileSchemaReport,
) -> bool:
    return any(
        _contains_phrase(normalized_task, column.name)
        for file_schema in schema.files
        for column in file_schema.schema.columns
    )


def _has_retention_hint(
    normalized_task: str,
    file_names: list[str],
) -> bool:
    if not re.search(r"\b(?:keep|retain|all rows|all)\b", normalized_task):
        return False
    return any(_contains_phrase(normalized_task, file_name) for file_name in file_names)


def _contains_phrase(normalized_task: str, phrase: str) -> bool:
    normalized_phrase = _normalize_text(phrase.replace("_", " "))
    normalized_name = _normalize_text(phrase)
    patterns = {
        rf"\b{re.escape(normalized_phrase)}\b",
        rf"\b{re.escape(normalized_name)}\b",
    }
    return any(re.search(pattern, normalized_task) for pattern in patterns)


def _format_names(names: list[str]) -> str:
    if not names:
        return "the input files"
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
