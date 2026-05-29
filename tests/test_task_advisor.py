from copy import deepcopy
import os
from pathlib import Path

from snapscript.core.models import (
    ColumnInfo,
    MultiFileSchemaReport,
    NamedSchemaReport,
    SchemaReport,
)
from snapscript.core.task_advisor import TaskAdvice, advise_task


def _single_schema() -> SchemaReport:
    return SchemaReport(
        filename="/tmp/private/orders.csv",
        file_type="csv",
        row_count=3,
        file_size_bytes=128,
        columns=[
            ColumnInfo(name="order_id", dtype="int64"),
            ColumnInfo(name="pid", dtype="object"),
            ColumnInfo(name="amount", dtype="int64"),
            ColumnInfo(name="status", dtype="object"),
        ],
    )


def _multi_schema() -> MultiFileSchemaReport:
    orders_schema = SchemaReport(
        filename="/tmp/private/orders.csv",
        file_type="csv",
        row_count=3,
        file_size_bytes=128,
        columns=[
            ColumnInfo(name="order_id", dtype="int64"),
            ColumnInfo(name="pid", dtype="object"),
            ColumnInfo(name="amount", dtype="int64"),
        ],
    )
    products_schema = SchemaReport(
        filename="/tmp/private/products.csv",
        file_type="csv",
        row_count=2,
        file_size_bytes=128,
        columns=[
            ColumnInfo(name="pid", dtype="object"),
            ColumnInfo(name="product_name", dtype="object"),
        ],
    )
    return MultiFileSchemaReport(
        files=[
            NamedSchemaReport(name="orders", schema=orders_schema),
            NamedSchemaReport(name="products", schema=products_schema),
        ]
    )


def _all_advice_text(advice: TaskAdvice) -> str:
    parts = [advice.quality, *advice.missing_details, *advice.suggestions]
    if advice.suggested_task is not None:
        parts.append(advice.suggested_task)
    return "\n".join(parts)


def test_empty_task_returns_too_vague() -> None:
    advice = advise_task("   ", _single_schema())

    assert advice.quality == "too_vague"
    assert "desired operation" in advice.missing_details


def test_clean_this_returns_too_vague() -> None:
    advice = advise_task("clean this", _single_schema())

    assert advice.quality == "too_vague"
    assert "desired operation" in advice.missing_details


def test_clear_single_file_filter_task_returns_good() -> None:
    advice = advise_task(
        "Filter rows where amount is greater than 1000",
        _single_schema(),
    )

    assert advice.quality == "good"
    assert advice.missing_details == []


def test_good_single_file_advice_has_no_python_code() -> None:
    advice = advise_task(
        "Filter rows where amount is greater than 1000",
        _single_schema(),
    )

    advice_text = _all_advice_text(advice).lower()
    assert "```" not in advice_text
    assert "import " not in advice_text
    assert "pd." not in advice_text
    assert "def " not in advice_text


def test_good_single_file_advice_has_no_real_file_path() -> None:
    advice = advise_task(
        "Filter rows where amount is greater than 1000",
        _single_schema(),
    )

    advice_text = _all_advice_text(advice)
    assert "/tmp/private/orders.csv" not in advice_text
    assert str(Path("/tmp/private/orders.csv")) not in advice_text


def test_vague_merge_returns_needs_detail_or_too_vague() -> None:
    advice = advise_task("merge these files", _multi_schema())

    assert advice.quality in {"needs_detail", "too_vague"}


def test_vague_merge_advice_includes_missing_join_key() -> None:
    advice = advise_task("merge these files", _multi_schema())

    assert "join key" in advice.missing_details


def test_vague_merge_advice_includes_missing_join_type() -> None:
    advice = advise_task("merge these files", _multi_schema())

    assert "join type" in advice.missing_details


def test_clear_two_file_join_task_returns_good() -> None:
    advice = advise_task(
        "Merge orders and products using pid with a left join and keep all orders",
        _multi_schema(),
    )

    assert advice.quality == "good"
    assert advice.missing_details == []


def test_multi_file_advice_uses_logical_file_names() -> None:
    advice = advise_task("merge these files", _multi_schema())

    advice_text = _all_advice_text(advice)
    assert "orders" in advice_text
    assert "products" in advice_text
    assert "/tmp/private" not in advice_text


def test_suggested_task_contains_no_code_pandas_or_real_paths() -> None:
    advice = advise_task("merge these files", _multi_schema())

    assert advice.suggested_task is not None
    suggested = advice.suggested_task.lower()
    assert "```" not in suggested
    assert "import " not in suggested
    assert "pd." not in suggested
    assert "pandas" not in suggested
    assert "/tmp/private" not in suggested
    assert "orders.csv" not in suggested
    assert "products.csv" not in suggested


def test_task_advisor_has_no_provider_or_execution_pipeline_imports() -> None:
    source = Path("src/snapscript/core/task_advisor.py").read_text(
        encoding="utf-8"
    )

    assert "anthropic" not in source.lower()
    assert "openai" not in source.lower()
    assert "task_rewriter" not in source
    assert "prompt_builder" not in source
    assert "retry_handler" not in source
    assert "safety_checker" not in source
    assert "execution_backend" not in source
    assert "sandbox_executor" not in source
    assert ".generate(" not in source
    assert ".execute(" not in source


def test_advisor_does_not_mutate_schema_object() -> None:
    schema = _multi_schema()
    before = deepcopy(schema)

    advise_task("merge these files", schema)

    assert schema == before


def test_advisor_does_not_require_provider_credentials(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    advice = advise_task(
        "Filter rows where amount is greater than 1000",
        _single_schema(),
    )

    assert "ANTHROPIC_API_KEY" not in os.environ
    assert advice.quality == "good"
