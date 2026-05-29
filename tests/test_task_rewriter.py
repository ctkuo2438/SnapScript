from copy import deepcopy
from pathlib import Path

import pytest

from snapscript.config import AppConfig
from snapscript.core import task_rewriter
from snapscript.core.models import (
    ColumnInfo,
    MultiFileSchemaReport,
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


def _mock_provider(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    calls: list[dict[str, str]] | None = None,
) -> None:
    def fake_call_provider(
        system_prompt: str,
        user_prompt: str,
        model: str | None,
    ) -> tuple[str, str, str]:
        if calls is not None:
            calls.append(
                {
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "model": "" if model is None else model,
                }
            )
        return text, "anthropic", model or "default-model"

    monkeypatch.setattr(task_rewriter, "_call_provider", fake_call_provider)


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
        task_rewriter,
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
    assert 'name="orders"' in user_prompt
    assert 'name="products"' in user_prompt


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


def test_rewritten_task_rejects_invented_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider(monkeypatch, "Filter rows where discount is greater than 0.")

    with pytest.raises(TaskRewriteError, match="unknown column"):
        rewrite_task("filter discounts", _single_schema())


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


def test_call_provider_uses_configured_anthropic_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _TextBlock:
        text = "Filter rows where amount is greater than 1000."

    class _Response:
        content = [_TextBlock()]

    class _Messages:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def create(self, **kwargs: object) -> _Response:
            self.calls.append(kwargs)
            return _Response()

    class _FakeAnthropic:
        instances: list["_FakeAnthropic"] = []

        def __init__(self) -> None:
            self.messages = _Messages()
            self.instances.append(self)

    _FakeAnthropic.instances = []
    monkeypatch.setattr(task_rewriter, "Anthropic", _FakeAnthropic)
    monkeypatch.setattr(
        task_rewriter,
        "AppConfig",
        lambda: AppConfig(default_model="default-model", max_tokens=1234),
    )

    text, provider, model = task_rewriter._call_provider("system", "user", None)

    assert text == "Filter rows where amount is greater than 1000."
    assert provider == "anthropic"
    assert model == "default-model"
    call = _FakeAnthropic.instances[0].messages.calls[0]
    assert call["model"] == "default-model"
    assert call["max_tokens"] == 1234
    assert call["temperature"] == 0.0
    assert call["system"] == "system"
    assert call["messages"] == [{"role": "user", "content": "user"}]


def test_call_provider_wraps_sdk_failure_without_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenAnthropic:
        def __init__(self) -> None:
            raise RuntimeError("ANTHROPIC_API_KEY=sk-ant-secret")

    monkeypatch.setattr(task_rewriter, "Anthropic", BrokenAnthropic)

    with pytest.raises(TaskRewriteError) as exc_info:
        task_rewriter._call_provider("system", "user", None)

    assert str(exc_info.value) == "Task rewrite provider call failed"
    assert exc_info.value.__cause__ is None
    assert "sk-ant" not in str(exc_info.value)
    assert "ANTHROPIC_API_KEY" not in str(exc_info.value)
