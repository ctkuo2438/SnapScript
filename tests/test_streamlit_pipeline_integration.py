from pathlib import Path

import pandas as pd
import pytest

from snapscript.core.models import (
    ColumnInfo,
    ExecutionResult,
    InputFileSpec,
    MultiFileSchemaReport,
    NamedSchemaReport,
    PromptPayload,
    SchemaReport,
)
from snapscript.interfaces import web


class FakeUploadedFile:
    def __init__(self, name: str, file_bytes: bytes) -> None:
        self.name = name
        self._file_bytes = file_bytes

    def getvalue(self) -> bytes:
        return self._file_bytes


class FakeStreamlit:
    def __init__(
        self,
        button_clicked: bool = False,
        uploaded_file: FakeUploadedFile | None = None,
        task_text: str = "",
        input_mode: str = "Single file",
    ) -> None:
        self.session_state: dict[str, object] = {}
        self.calls: list[
            tuple[str, tuple[object, ...], dict[str, object]]
        ] = []
        self.button_clicked = button_clicked
        self.uploaded_file = uploaded_file
        self.task_text = task_text
        self.input_mode = input_mode

    def title(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("title", args, kwargs))

    def write(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("write", args, kwargs))

    def file_uploader(
        self, *args: object, **kwargs: object
    ) -> FakeUploadedFile | None:
        self.calls.append(("file_uploader", args, kwargs))
        return self.uploaded_file

    def radio(self, *args: object, **kwargs: object) -> str:
        self.calls.append(("radio", args, kwargs))
        return self.input_mode

    def text_area(self, *args: object, **kwargs: object) -> str:
        self.calls.append(("text_area", args, kwargs))
        return self.task_text

    def button(self, *args: object, **kwargs: object) -> bool:
        self.calls.append(("button", args, kwargs))
        return self.button_clicked and not bool(kwargs.get("disabled", False))

    def caption(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("caption", args, kwargs))

    def subheader(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("subheader", args, kwargs))

    def info(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("info", args, kwargs))

    def error(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("error", args, kwargs))

    def success(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("success", args, kwargs))

    def dataframe(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("dataframe", args, kwargs))

    def download_button(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("download_button", args, kwargs))


@pytest.fixture(autouse=True)
def isolate_audit_log(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(web, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")


def _schema() -> SchemaReport:
    return SchemaReport(
        filename="input.csv",
        file_type="csv",
        row_count=1,
        file_size_bytes=20,
    )


def _multi_schema() -> MultiFileSchemaReport:
    return MultiFileSchemaReport(
        files=[
            NamedSchemaReport(
                name="orders",
                schema=SchemaReport(
                    filename="orders.csv",
                    file_type="csv",
                    row_count=3,
                    file_size_bytes=64,
                    columns=[
                        ColumnInfo(name="order_id", dtype="int64"),
                        ColumnInfo(name="pid", dtype="object"),
                        ColumnInfo(name="amount", dtype="int64"),
                    ],
                ),
            ),
            NamedSchemaReport(
                name="products",
                schema=SchemaReport(
                    filename="products.csv",
                    file_type="csv",
                    row_count=2,
                    file_size_bytes=64,
                    columns=[
                        ColumnInfo(name="pid", dtype="object"),
                        ColumnInfo(name="product_name", dtype="object"),
                    ],
                ),
            ),
        ]
    )


def test_run_uploaded_task_calls_existing_core_flow_with_temp_paths(
    monkeypatch,
) -> None:
    upload_bytes = b"order_id,amount\n1,1500\n"
    output_bytes = b"order_id,amount\n1,1500\n"
    calls: list[tuple[str, object]] = []

    def fake_inspect(input_path: Path) -> SchemaReport:
        calls.append(("inspect", input_path))
        assert input_path.name == "input.csv"
        assert input_path.read_bytes() == upload_bytes
        return _schema()

    def fake_build(task_text: str, schema: SchemaReport) -> PromptPayload:
        calls.append(("build", task_text))
        assert task_text == "Keep large orders."
        assert schema.filename == "input.csv"
        return PromptPayload(system_prompt="system", user_prompt="user")

    def fake_run(
        prompt: PromptPayload,
        input_path: Path,
        output_path: Path,
    ) -> ExecutionResult:
        calls.append(("run", (prompt, input_path, output_path)))
        assert prompt.user_prompt == "user"
        assert input_path.name == "input.csv"
        assert output_path.name == "output.csv"
        assert output_path.parent == input_path.parent
        output_path.write_bytes(output_bytes)
        return ExecutionResult(
            success=True,
            output_files=[output_path],
        )

    monkeypatch.setattr(web.schema_inspector, "inspect", fake_inspect)
    monkeypatch.setattr(web.prompt_builder, "build", fake_build)
    monkeypatch.setattr(web.retry_handler, "run", fake_run)

    result, returned_output, output_file_name = web.run_uploaded_task(
        upload_bytes,
        ".csv",
        " Keep large orders. ",
        uploaded_file_name="orders.csv",
    )

    assert result.success is True
    assert returned_output == output_bytes
    assert output_file_name == "orders_snapscript_output.csv"
    assert [name for name, _value in calls] == ["inspect", "build", "run"]


def test_run_uploaded_tasks_many_mocked_join_flow_uses_safe_pipeline(
    monkeypatch,
) -> None:
    orders_bytes = (
        b"order_id,pid,amount\n"
        b"1,p1,100\n"
        b"2,p2,200\n"
        b"3,p3,300\n"
    )
    products_bytes = b"pid,product_name\np1,Keyboard\np2,Mouse\n"
    calls: list[str] = []
    seen_specs: list[list[InputFileSpec]] = []

    def fake_inspect_many(specs: list[InputFileSpec]) -> MultiFileSchemaReport:
        calls.append("inspect_many")
        seen_specs.append(specs)
        assert [spec.name for spec in specs] == ["orders", "products"]
        assert all(spec.path.parent == specs[0].path.parent for spec in specs)
        assert specs[0].path.read_bytes() == orders_bytes
        assert specs[1].path.read_bytes() == products_bytes
        return _multi_schema()

    def fake_build_many(
        task_text: str,
        multi_schema: MultiFileSchemaReport,
    ) -> PromptPayload:
        calls.append("build_many")
        assert "inner join" in task_text
        assert [file_schema.name for file_schema in multi_schema.files] == [
            "orders",
            "products",
        ]
        return PromptPayload(system_prompt="system", user_prompt="user")

    def fake_run_many(
        prompt: PromptPayload,
        specs: list[InputFileSpec],
        output_path: Path,
    ) -> ExecutionResult:
        calls.append("run_many")
        seen_specs.append(specs)
        assert prompt.user_prompt == "user"
        orders = pd.read_csv(specs[0].path)
        products = pd.read_csv(specs[1].path)
        joined = orders.merge(products, on="pid", how="inner")
        joined.to_csv(output_path, index=False)
        return ExecutionResult(success=True, output_files=[output_path])

    monkeypatch.setattr(web.schema_inspector, "inspect_many", fake_inspect_many)
    monkeypatch.setattr(web.prompt_builder, "build_many", fake_build_many)
    monkeypatch.setattr(web.retry_handler, "run_many", fake_run_many)

    result, output_bytes, output_file_name = web.run_uploaded_tasks_many(
        first_file_bytes=orders_bytes,
        first_suffix=".csv",
        first_logical_name="orders",
        first_uploaded_file_name="orders.csv",
        second_file_bytes=products_bytes,
        second_suffix=".csv",
        second_logical_name="products",
        second_uploaded_file_name="products.csv",
        task_text='Please merge orders and products using the "pid" column with an inner join.',
    )

    assert result.success is True
    assert output_file_name == "snapscript_output.csv"
    assert output_bytes is not None
    preview = web.load_output_preview(output_bytes, ".csv")
    assert len(preview) == 2
    assert list(preview.columns) == ["order_id", "pid", "amount", "product_name"]
    assert "p3" not in set(preview["pid"])
    assert calls == ["inspect_many", "build_many", "run_many"]
    assert seen_specs[0] is seen_specs[1]


def test_run_uploaded_task_populates_audit_metadata_without_raw_rows(
    monkeypatch,
) -> None:
    upload_bytes = b"order_id,amount\n1,1500\n"
    output_bytes = b"order_id,amount\n1,1500\n"
    audit_metadata: dict[str, object] = {}

    def fake_inspect(_input_path: Path) -> SchemaReport:
        schema = _schema()
        schema.columns = []
        schema.sample_rows = [{"order_id": 1, "amount": 1500}]
        return schema

    def fake_build(_task_text: str, _schema_report: SchemaReport) -> PromptPayload:
        return PromptPayload(system_prompt="system", user_prompt="user")

    def fake_run(
        _prompt: PromptPayload,
        _input_path: Path,
        output_path: Path,
    ) -> ExecutionResult:
        assert audit_metadata["provider_called"] is True
        output_path.write_bytes(output_bytes)
        return ExecutionResult(success=True, output_files=[output_path])

    monkeypatch.setattr(web.schema_inspector, "inspect", fake_inspect)
    monkeypatch.setattr(web.prompt_builder, "build", fake_build)
    monkeypatch.setattr(web.retry_handler, "run", fake_run)

    result, returned_output, output_file_name = web.run_uploaded_task(
        upload_bytes,
        ".csv",
        "Keep large orders.",
        uploaded_file_name="orders.csv",
        audit_metadata=audit_metadata,
    )

    assert result.success is True
    assert returned_output == output_bytes
    assert output_file_name == "orders_snapscript_output.csv"
    assert audit_metadata["prompt_text"] == "system\n\nuser"
    assert audit_metadata["system_prompt"] == "system"
    assert audit_metadata["user_prompt"] == "user"
    schema_summary = audit_metadata["schema_summary"]
    assert isinstance(schema_summary, dict)
    assert "sample_rows" not in schema_summary
    assert "1500" not in str(schema_summary)


def test_run_uploaded_task_does_not_store_output_bytes_on_failure(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        web.schema_inspector,
        "inspect",
        lambda _input_path: _schema(),
    )
    monkeypatch.setattr(
        web.prompt_builder,
        "build",
        lambda _task_text, _schema_report: PromptPayload(
            system_prompt="system",
            user_prompt="user",
        ),
    )
    monkeypatch.setattr(
        web.retry_handler,
        "run",
        lambda _prompt, _input_path, _output_path: ExecutionResult(
            success=False,
            stderr="Execution failed",
            exit_code=3,
        ),
    )

    result, returned_output, output_file_name = web.run_uploaded_task(
        b"order_id,amount\n1,1500\n",
        ".csv",
        "Keep large orders.",
        uploaded_file_name="orders.csv",
    )

    assert result.success is False
    assert returned_output is None
    assert output_file_name is None


def test_main_generate_click_stores_output_bytes_after_success(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,1500\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep large orders.",
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda _file_bytes, _suffix, _task_text, uploaded_file_name=None, audit_metadata=None: (
            ExecutionResult(success=True),
            b"order_id,amount\n1,1500\n",
            web.derive_output_file_name(uploaded_file_name, ".csv"),
        ),
    )

    web.main()

    assert fake_st.session_state["output_bytes"] == b"order_id,amount\n1,1500\n"
    assert fake_st.session_state["output_file_name"] == (
        "orders_snapscript_output.csv"
    )
    assert fake_st.session_state["result_preview"] is not None
    assert fake_st.session_state["error_message"] is None
    assert ("success", ("Generation succeeded.",), {}) in fake_st.calls


def test_main_generate_failure_sets_error_without_output_bytes(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,1500\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep large orders.",
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda _file_bytes, _suffix, _task_text, uploaded_file_name=None, audit_metadata=None: (
            ExecutionResult(
                success=False,
                stderr="Execution failed",
                exit_code=3,
            ),
            None,
            None,
        ),
    )

    web.main()

    assert fake_st.session_state["output_bytes"] is None
    assert fake_st.session_state["output_file_name"] is None
    assert fake_st.session_state["result_preview"] is None
    expected_error = "Execution failed in the sandbox. Summary: Execution failed"
    assert fake_st.session_state["error_message"] == expected_error
    assert ("error", (expected_error,), {}) in fake_st.calls


def test_main_does_not_call_pipeline_without_generate_click(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,1500\n")
    fake_st = FakeStreamlit(
        button_clicked=False,
        uploaded_file=uploaded,
        task_text="Keep large orders.",
    )
    calls: list[tuple[bytes, str, str]] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda file_bytes, suffix, task_text, uploaded_file_name=None, audit_metadata=None: calls.append(
            (file_bytes, suffix, task_text)
        ),
    )

    web.main()

    assert calls == []


def test_main_does_not_call_pipeline_when_upload_missing(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(
        button_clicked=True,
        task_text="Keep large orders.",
    )
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda *_args: calls.append(_args),
    )

    web.main()

    assert calls == []


def test_main_does_not_call_pipeline_when_task_blank(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,amount\n1,1500\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="   ",
    )
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda *_args: calls.append(_args),
    )

    web.main()

    assert calls == []


def test_web_uses_retry_handler_without_direct_provider_or_sandbox_calls() -> None:
    source = Path("src/snapscript/interfaces/web.py").read_text(encoding="utf-8")

    assert "from snapscript.core import" in source
    assert "retry_handler.run(" in source
    assert "Anthropic" not in source
    assert "anthropic" not in source
    assert "code_generator" not in source
    assert "safety_checker" not in source
    assert "sandbox_executor" not in source
    assert ".generate(" not in source
    assert ".execute(" not in source
