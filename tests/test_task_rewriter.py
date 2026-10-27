from copy import deepcopy
import json
from pathlib import Path

import pytest

from snapscript.config import AppConfig
from snapscript.core import task_rewriter, provider
from snapscript.core.models import (
    ColumnInfo,
    MultiFileSchemaReport,
    ProviderReply,
    ProviderCallMetrics,
    NamedSchemaReport,
    RewrittenTask,
    SchemaReport,
    TaskAdvice,
)
from snapscript.core.task_rewriter import TaskRewriteError, rewrite_task


def _single_schema() -> SchemaReport:
    return SchemaReport(
        filename="/tmp/private/orders.csv",
        file_type="csv",
        row_count=3,
        file_size_bytes=128,
        columns=[
            ColumnInfo(name="order_id", dtype="int64"),
            ColumnInfo(name="pid", dtype="object"),
            ColumnInfo(name="amount", dtype="int64", null_count=0),
            ColumnInfo(name="status", dtype="object", null_count=1),
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


def _event_schema() -> MultiFileSchemaReport:
    events_schema = SchemaReport(
        filename="/tmp/private/events.csv",
        file_type="csv",
        row_count=3,
        file_size_bytes=128,
        columns=[
            ColumnInfo(name="event_id", dtype="int64"),
            ColumnInfo(name="event_type", dtype="object"),
        ],
    )
    lookup_schema = SchemaReport(
        filename="/tmp/private/event_lookup.csv",
        file_type="csv",
        row_count=2,
        file_size_bytes=128,
        columns=[
            ColumnInfo(name="event_type", dtype="object"),
            ColumnInfo(name="category", dtype="object"),
        ],
    )
    return MultiFileSchemaReport(
        files=[
            NamedSchemaReport(name="events", schema=events_schema),
            NamedSchemaReport(name="event_lookup", schema=lookup_schema),
        ]
    )


def _mock_provider(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    calls: list[dict[str, str]] | None = None,
) -> None:
    def fake_call_provider(
        system_prompt: str,
        user_prompt: str,
        model: str | None,
        config: AppConfig,
    ) -> ProviderReply:
        if calls is not None:
            calls.append(
                {
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "model": "" if model is None else model,
                }
            )
        return ProviderReply(text, ProviderCallMetrics("anthropic", model or "default-model"))

    monkeypatch.setattr(task_rewriter, "_call_provider", fake_call_provider)


@pytest.mark.parametrize("text", [
    "Sum import value by country", "Filter rows where class label is A",
    "Count pandas sightings by region", 'Keep rows where status is "active"',
    "Keep rows where status is 'active'",
])
def test_rewrite_preserves_natural_language_and_quoted_values(monkeypatch, text):
    _mock_provider(monkeypatch, text)
    assert rewrite_task("Improve this task", _single_schema()).rewritten_task == text


@pytest.mark.parametrize("text,expected", [
    ('"Keep status active"', "Keep status active"),
    ("'Keep status active'", "Keep status active"),
    ('Task: Keep status "active"', 'Keep status "active"'),
])
def test_rewrite_strips_only_balanced_outer_quotes(text, expected):
    assert task_rewriter._strip_rewrite_output(text) == expected


@pytest.mark.parametrize("path", [
    "/etc/private", "/opt/private", "/mnt/private", "~/private",
    "C:/private/data", r"\\server\share\private", '"/home/private records/data"',
])
def test_rewrite_redacts_and_rejects_real_path_forms(path):
    text = f"Process values from {path}"
    assert "[path]" in task_rewriter._redact_paths_and_filenames(text)
    with pytest.raises(TaskRewriteError, match="paths"):
        task_rewriter._validate_rewritten_task(text)


def test_rewrite_task_returns_rewritten_task(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_provider(
        monkeypatch,
        "Filter rows where amount is greater than 1000.",
    )

    rewritten = rewrite_task("filter big orders", _single_schema())

    assert isinstance(rewritten, RewrittenTask)
    assert rewritten.rewritten_task == "Filter rows where amount is greater than 1000."


def test_rewrite_task_preserves_original_task(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_provider(monkeypatch, "Filter rows where amount is greater than 1000.")

    rewritten = rewrite_task("filter big orders", _single_schema())

    assert rewritten.original_task == "filter big orders"


def test_rewrite_task_records_provider_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_provider(monkeypatch, "Filter rows where amount is greater than 1000.")

    rewritten = rewrite_task(
        "filter big orders",
        _single_schema(),
        model="rewrite-model",
    )

    assert rewritten.provider == "anthropic"
    assert rewritten.model == "rewrite-model"


def test_provider_boundary_is_mocked_without_real_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        provider,
        "Anthropic",
        lambda: pytest.fail("Anthropic client should not be constructed"),
    )
    _mock_provider(monkeypatch, "Filter rows where amount is greater than 1000.")

    rewritten = rewrite_task("filter big orders", _single_schema())

    assert rewritten.rewritten_task.startswith("Filter rows")


def test_prompt_includes_schema_column_names(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, str]] = []
    _mock_provider(monkeypatch, "Filter rows where amount is greater than 1000.", calls)

    rewrite_task("filter big orders", _single_schema())

    user_prompt = calls[0]["user_prompt"]
    assert "amount" in user_prompt
    assert "status" in user_prompt
    assert "order_id" in user_prompt


def test_prompt_does_not_include_real_file_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []
    _mock_provider(monkeypatch, "Filter rows where amount is greater than 1000.", calls)

    rewrite_task("filter big orders", _single_schema())

    user_prompt = calls[0]["user_prompt"]
    assert "/tmp/private/orders.csv" not in user_prompt
    assert "orders.csv" not in user_prompt


def test_prompt_does_not_include_uploaded_display_filenames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []
    _mock_provider(monkeypatch, "Filter rows where amount is greater than 1000.", calls)
    schema = _single_schema()
    schema.filename = "customer_upload_2026.csv"

    rewrite_task("filter customer_upload_2026.csv", schema)

    user_prompt = calls[0]["user_prompt"]
    assert "customer_upload_2026.csv" not in user_prompt
    assert "[file]" in user_prompt


def test_prompt_redacts_paths_from_original_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []
    _mock_provider(monkeypatch, "Filter rows where amount is greater than 1000.", calls)

    rewrite_task(
        "Read /tmp/private/orders.csv and filter amount.",
        _single_schema(),
    )

    user_prompt = calls[0]["user_prompt"]
    assert "/tmp/private/orders.csv" not in user_prompt
    assert "orders.csv" not in user_prompt
    assert "[path]" in user_prompt


def test_multi_file_prompt_includes_logical_file_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []
    _mock_provider(
        monkeypatch,
        "Merge orders and products using pid with a left join.",
        calls,
    )

    rewrite_task("merge these", _multi_schema())

    user_prompt = calls[0]["user_prompt"]
    schema = json.loads(user_prompt.split("<schema>\n", 1)[1].split("\n</schema>", 1)[0])
    assert [file["logical_name"] for file in schema["files"]] == ["orders", "products"]


def test_multi_file_prompt_does_not_include_real_file_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []
    _mock_provider(
        monkeypatch,
        "Merge orders and products using pid with a left join.",
        calls,
    )

    rewrite_task("merge these", _multi_schema())

    user_prompt = calls[0]["user_prompt"]
    assert "/tmp/private/orders.csv" not in user_prompt
    assert "/tmp/private/products.csv" not in user_prompt
    assert "orders.csv" not in user_prompt
    assert "products.csv" not in user_prompt


def test_advice_missing_details_and_suggestions_are_included(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []
    _mock_provider(
        monkeypatch,
        "Merge orders and products using pid with a left join.",
        calls,
    )
    advice = TaskAdvice(
        quality="needs_detail",
        missing_details=["join key", "join type"],
        suggestions=["Name the shared column and join type."],
    )

    rewrite_task("merge these", _multi_schema(), advice=advice)

    user_prompt = calls[0]["user_prompt"]
    assert "join key" in user_prompt
    assert "join type" in user_prompt
    assert "Name the shared column and join type." in user_prompt


def test_markdown_fences_are_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_provider(
        monkeypatch,
        "```text\nFilter rows where amount is greater than 1000.\n```",
    )

    rewritten = rewrite_task("filter big orders", _single_schema())

    assert rewritten.rewritten_task == "Filter rows where amount is greater than 1000."


def test_rewritten_task_label_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_provider(
        monkeypatch,
        'Rewritten task: "Filter rows where amount is greater than 1000."',
    )

    rewritten = rewrite_task("filter big orders", _single_schema())

    assert rewritten.rewritten_task == "Filter rows where amount is greater than 1000."


@pytest.mark.parametrize(
    "provider_text",
    [
        "import pandas as pd\ndf = pd.read_csv(INPUT_PATH)",
        "Use pd.concat([orders, products]).",
        "def transform(df): return df",
    ],
)
def test_python_or_pandas_code_output_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    provider_text: str,
) -> None:
    _mock_provider(monkeypatch, provider_text)

    with pytest.raises(TaskRewriteError, match="must be natural language"):
        rewrite_task("filter big orders", _single_schema())


def test_empty_provider_output_raises_task_rewrite_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider(monkeypatch, "   ")

    with pytest.raises(TaskRewriteError, match="empty"):
        rewrite_task("filter big orders", _single_schema())


def test_provider_exception_is_mapped_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_provider(
        _system_prompt: str,
        _user_prompt: str,
        _model: str | None,
    ) -> tuple[str, str, str]:
        raise RuntimeError("ANTHROPIC_API_KEY=sk-ant-secret")

    monkeypatch.setattr(task_rewriter, "_call_provider", failing_provider)

    with pytest.raises(TaskRewriteError) as exc_info:
        rewrite_task("filter big orders", _single_schema())

    assert str(exc_info.value) == "Task rewrite provider call failed"
    assert exc_info.value.__cause__ is None
    assert "sk-ant" not in str(exc_info.value)
    assert "ANTHROPIC_API_KEY" not in str(exc_info.value)


def test_task_rewriter_has_no_execution_pipeline_imports_or_calls() -> None:
    source = Path("src/snapscript/core/task_rewriter.py").read_text()

    assert "streamlit" not in source
    assert "argparse" not in source
    assert "rich" not in source
    assert "prompt_builder" not in source
    assert "retry_handler" not in source
    assert "safety_checker" not in source
    assert "execution_backend" not in source
    assert "sandbox_executor" not in source
    assert "code_generator.generate" not in source
    assert ".execute(" not in source


def test_rewriter_does_not_create_output_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _mock_provider(monkeypatch, "Filter rows where amount is greater than 1000.")

    rewrite_task("filter big orders", _single_schema())

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "rewritten_text",
    [
        "Filter rows using a threshold of 1000 for amount.",
        "Create column total by multiplying amount by 2.",
        "Keep rows where amount > 1000, sorted by descending order.",
        "保留 amount 大於 1000 的資料。",
    ],
)
def test_rewritten_task_accepts_natural_language_and_new_output_columns(
    monkeypatch: pytest.MonkeyPatch,
    rewritten_text: str,
) -> None:
    _mock_provider(monkeypatch, rewritten_text)

    rewritten = rewrite_task(rewritten_text, _single_schema())

    assert rewritten.original_task == rewritten_text
    assert rewritten.rewritten_task == rewritten_text


def test_rewritten_task_accepts_article_before_join_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider(
        monkeypatch,
        "Merge events and event_lookup on the event_type column with an inner join.",
    )

    rewritten = rewrite_task("merge them on event_type", _event_schema())

    assert rewritten.rewritten_task == (
        "Merge events and event_lookup on the event_type column with an inner join."
    )


def test_rewritten_task_accepts_using_the_join_column_phrase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider(
        monkeypatch,
        (
            "Perform an inner join between events and event_lookup using "
            "the event_type column. Keep all matching rows."
        ),
    )

    rewritten = rewrite_task("merge them on event_type", _event_schema())

    assert rewritten.rewritten_task == (
        "Perform an inner join between events and event_lookup using "
        "the event_type column. Keep all matching rows."
    )


def test_rewritten_task_accepts_common_join_sentence_without_false_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider(
        monkeypatch,
        (
            "Perform an inner join between events and event_lookup on the "
            "event_type column. Retain all columns from both files in the output."
        ),
    )

    rewritten = rewrite_task("merge them on event_type", _event_schema())

    assert rewritten.rewritten_task == (
        "Perform an inner join between events and event_lookup on the "
        "event_type column. Retain all columns from both files in the output."
    )


def test_rewritten_task_rejects_file_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider(monkeypatch, "Filter rows in orders.csv where amount is greater than 1000.")

    with pytest.raises(TaskRewriteError, match="file paths"):
        rewrite_task("filter big orders", _single_schema())


def test_rewritten_task_rejects_real_local_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider(
        monkeypatch,
        "Filter rows in /tmp/private/orders.csv where amount is greater than 1000.",
    )

    with pytest.raises(TaskRewriteError, match="file paths"):
        rewrite_task("filter big orders", _single_schema())


def test_rewrite_does_not_mutate_schema_or_advice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = _multi_schema()
    advice = TaskAdvice(
        quality="needs_detail",
        missing_details=["join key"],
        suggestions=["Name the join key."],
    )
    before_schema = deepcopy(schema)
    before_advice = deepcopy(advice)
    _mock_provider(
        monkeypatch,
        "Merge orders and products using pid with a left join.",
    )

    rewrite_task("merge these", schema, advice=advice)

    assert schema == before_schema
    assert advice == before_advice


def test_rewrite_uses_shared_provider_and_keeps_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    from helpers.provider_helpers import FakeAnthropic, Response

    FakeAnthropic.instances = []
    FakeAnthropic.response = Response("Filter rows where amount is greater than 1000.", model="actual-rewrite-model")
    monkeypatch.setattr(provider, "Anthropic", FakeAnthropic)
    result = rewrite_task("filter orders", _single_schema(), config=AppConfig(provider_timeout_seconds=2))
    client = FakeAnthropic.instances[-1]
    assert result.api_call.model == result.model == "actual-rewrite-model"
    assert result.api_call.input_tokens == 12
    assert client.options == {"timeout": 2, "max_retries": 1}
    assert client.closed


def test_rewrite_wraps_sdk_failure_with_safe_category(monkeypatch: pytest.MonkeyPatch) -> None:
    from helpers.provider_helpers import FakeAnthropic

    FakeAnthropic.response = RuntimeError("ANTHROPIC_API_KEY=sk-ant-secret")
    monkeypatch.setattr(provider, "Anthropic", FakeAnthropic)
    with pytest.raises(TaskRewriteError) as captured:
        rewrite_task("filter orders", _single_schema())
    assert str(captured.value) == "Task rewrite provider call failed"
    assert captured.value.__cause__ is None
    assert captured.value.category == "provider_failure"
    assert captured.value.api_calls[0].model == AppConfig().default_model
    assert FakeAnthropic.instances[-1].closed


def test_rewritten_task_accepts_join_type_words_as_non_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider(
        monkeypatch,
        (
            "Perform an inner join between events and event_lookup on the "
            "event_type column. Retain all columns from both files."
        ),
    )

    rewritten = rewrite_task("merge them on event_type", _event_schema())

    assert rewritten.rewritten_task == (
        "Perform an inner join between events and event_lookup on the "
        "event_type column. Retain all columns from both files."
    )
