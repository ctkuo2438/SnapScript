from pathlib import Path

import pandas as pd
import pytest

from snapscript.core.models import (
    ExecutionResult,
    InputFileSpec,
    MultiFileSchemaReport,
    PromptPayload,
)
from snapscript.interfaces import web
from helpers.streamlit_helpers import (
    FakeStreamlit,
    FakeUploadedFile,
    _button_disabled,
    _has_placeholder_message,
    _multi_schema,
)


@pytest.fixture(autouse=True)
def isolate_audit_log(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(web, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")


def test_main_stores_valid_uploaded_file_without_pipeline_calls(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(uploaded_file=uploaded)
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert fake_st.session_state["uploaded_file_name"] == "orders.csv"
    assert fake_st.session_state["uploaded_file_suffix"] == ".csv"
    assert fake_st.session_state["uploaded_file_bytes"] == uploaded.getvalue()
    assert (
        "success",
        ("Uploaded orders.csv (20 bytes).",),
        {},
    ) in fake_st.calls
    assert not any(
        name == "download_button" for name, _args, _kwargs in fake_st.calls
    )

def test_main_displays_invalid_upload_error_without_pipeline_calls(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.txt", b"not,csv\n")
    fake_st = FakeStreamlit(uploaded_file=uploaded)
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert fake_st.session_state["uploaded_file_name"] is None
    assert fake_st.session_state["uploaded_file_suffix"] is None
    assert fake_st.session_state["uploaded_file_bytes"] is None
    assert fake_st.session_state["error_message"] == "Unsupported file type: .txt"
    assert ("error", ("Unsupported file type: .txt",), {}) in fake_st.calls
    assert not _has_placeholder_message(fake_st.calls)

def test_main_stores_task_text_in_session_state(monkeypatch) -> None:
    fake_st = FakeStreamlit(task_text="  Keep large orders. ")
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert fake_st.session_state["task_text"] == "  Keep large orders. "

def test_main_disables_generate_when_upload_is_missing(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(
        button_clicked=True,
        task_text="Keep large orders.",
    )
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert _button_disabled(fake_st.calls) is True
    assert not _has_placeholder_message(fake_st.calls)

def test_main_disables_generate_when_task_text_is_blank(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="   ",
    )
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert _button_disabled(fake_st.calls) is True
    assert not _has_placeholder_message(fake_st.calls)

def test_main_disables_generate_when_run_limit_reached(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(uploaded_file=uploaded, task_text="Keep rows.")
    fake_st.session_state["run_count"] = web.MAX_RUNS_PER_SESSION
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert _button_disabled(fake_st.calls) is True
    assert fake_st.session_state["error_message"] == (
        "Run limit reached for this session."
    )

def test_main_generate_click_validates_then_calls_pipeline_helper(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text=" Keep large orders. ",
    )
    calls: list[tuple[bytes, str, str]] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda file_bytes, suffix, task_text, uploaded_file_name=None, audit_metadata=None: (
            calls.append((file_bytes, suffix, task_text))
            or (
                web.ExecutionResult(success=True),
                b"ok\n",
                "snapscript_output.csv",
            )
        ),
    )

    web.main()

    assert _button_disabled(fake_st.calls) is False
    assert fake_st.session_state["task_text"] == " Keep large orders. "
    assert fake_st.session_state["error_message"] is None
    assert calls == [
        (
            b"order_id,total\n1,10\n",
            ".csv",
            " Keep large orders. ",
        )
    ]
    assert not _has_placeholder_message(fake_st.calls)

def test_run_uploaded_tasks_many_calls_multi_file_core_flow_with_temp_paths(
    monkeypatch,
) -> None:
    orders_bytes = b"order_id,pid\n1,p1\n"
    products_bytes = b"pid,product_name\np1,Keyboard\n"
    output_bytes = b"order_id,pid,product_name\n1,p1,Keyboard\n"
    calls: list[str] = []
    seen_specs: list[list[InputFileSpec]] = []

    def fake_inspect_many(specs: list[InputFileSpec]) -> MultiFileSchemaReport:
        calls.append("inspect_many")
        seen_specs.append(specs)
        assert [spec.name for spec in specs] == ["orders", "products"]
        assert [spec.display_filename for spec in specs] == [
            "orders.csv",
            "products.csv",
        ]
        assert specs[0].path.name == "input_1_orders.csv"
        assert specs[1].path.name == "input_2_products.csv"
        assert specs[0].path.read_bytes() == orders_bytes
        assert specs[1].path.read_bytes() == products_bytes
        return _multi_schema()

    def fake_build_many(
        task_text: str,
        multi_schema: MultiFileSchemaReport,
    ) -> PromptPayload:
        calls.append("build_many")
        assert task_text == "Merge orders and products."
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
        assert output_path.name == "output.csv"
        output_path.write_bytes(output_bytes)
        return ExecutionResult(success=True, output_files=[output_path])

    monkeypatch.setattr(web.schema_inspector, "inspect_many", fake_inspect_many)
    monkeypatch.setattr(web.prompt_builder, "build_many", fake_build_many)
    monkeypatch.setattr(web.retry_handler, "run_many", fake_run_many)

    result, returned_output, output_file_name = web.run_uploaded_tasks_many(
        first_file_bytes=orders_bytes,
        first_suffix=".csv",
        first_logical_name=" orders ",
        first_uploaded_file_name="orders.csv",
        second_file_bytes=products_bytes,
        second_suffix=".csv",
        second_logical_name="products",
        second_uploaded_file_name="products.csv",
        task_text=" Merge orders and products. ",
    )

    assert result.success is True
    assert returned_output == output_bytes
    assert output_file_name == "snapscript_output.csv"
    assert calls == ["inspect_many", "build_many", "run_many"]
    assert seen_specs[0] is seen_specs[1]

def test_main_two_file_generate_click_validates_then_calls_multi_file_helper(
    monkeypatch,
) -> None:
    orders = FakeUploadedFile("orders.csv", b"order_id,pid\n1,p1\n")
    products = FakeUploadedFile("products.csv", b"pid,product_name\np1,Keyboard\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        input_mode="Two files",
        first_uploaded_file=orders,
        second_uploaded_file=products,
        first_logical_name="orders",
        second_logical_name="products",
        task_text=" Merge orders and products. ",
    )
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_tasks_many",
        lambda **kwargs: (
            calls.append(
                (
                    str(kwargs["first_logical_name"]),
                    str(kwargs["second_logical_name"]),
                    str(kwargs["task_text"]),
                )
            )
            or (
                ExecutionResult(success=True),
                b"order_id,pid,product_name\n1,p1,Keyboard\n",
                "snapscript_output.csv",
            )
        ),
    )

    web.main()

    assert _button_disabled(fake_st.calls) is False
    assert calls == [("orders", "products", " Merge orders and products. ")]
    assert fake_st.session_state["first_uploaded_file_bytes"] == orders.getvalue()
    assert fake_st.session_state["second_uploaded_file_bytes"] == products.getvalue()
    assert fake_st.session_state["error_message"] is None

@pytest.mark.parametrize(
    ("first_name", "second_name", "second_file", "expected_error"),
    [
        ("orders", "products", None, "Upload both files before generating."),
        ("", "products", FakeUploadedFile("products.csv", b"x\n"), "Logical names are required"),
        ("orders", "", FakeUploadedFile("products.csv", b"x\n"), "Logical names are required"),
        ("orders", "orders", FakeUploadedFile("products.csv", b"x\n"), "Duplicate logical input name"),
        ("Orders", "products", FakeUploadedFile("products.csv", b"x\n"), "Invalid logical input name"),
    ],
)
def test_main_two_file_validation_blocks_before_pipeline_helper(
    monkeypatch,
    first_name: str,
    second_name: str,
    second_file: FakeUploadedFile | None,
    expected_error: str,
) -> None:
    fake_st = FakeStreamlit(
        button_clicked=True,
        input_mode="Two files",
        first_uploaded_file=FakeUploadedFile("orders.csv", b"x\n"),
        second_uploaded_file=second_file,
        first_logical_name=first_name,
        second_logical_name=second_name,
        task_text="Merge files.",
    )
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_tasks_many",
        lambda **kwargs: calls.append(kwargs),
    )

    web.main()

    assert _button_disabled(fake_st.calls) is True
    assert calls == []
    assert expected_error in str(fake_st.session_state["error_message"])

def test_main_two_file_unsupported_suffix_blocks_before_pipeline_helper(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(
        button_clicked=True,
        input_mode="Two files",
        first_uploaded_file=FakeUploadedFile("orders.csv", b"x\n"),
        second_uploaded_file=FakeUploadedFile("products.txt", b"x\n"),
        first_logical_name="orders",
        second_logical_name="products",
        task_text="Merge files.",
    )
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_tasks_many",
        lambda **kwargs: calls.append(kwargs),
    )

    web.main()

    assert _button_disabled(fake_st.calls) is True
    assert calls == []
    assert fake_st.session_state["error_message"] == "Unsupported file type: .txt"

def test_main_two_file_upload_without_generate_does_not_call_pipeline_helper(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(
        button_clicked=False,
        input_mode="Two files",
        first_uploaded_file=FakeUploadedFile("orders.csv", b"x\n"),
        second_uploaded_file=FakeUploadedFile("products.csv", b"x\n"),
        first_logical_name="orders",
        second_logical_name="products",
        task_text="Merge files.",
    )
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_tasks_many",
        lambda **kwargs: calls.append(kwargs),
    )

    web.main()

    assert calls == []

def test_main_single_file_mode_clears_stale_two_file_validation_error(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(
        input_mode="Single file",
        uploaded_file=None,
        task_text="Merge files.",
    )
    fake_st.session_state["error_message"] = "Upload both files before generating."
    fake_st.session_state["error_source"] = web.ERROR_SOURCE_VALIDATION
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert _button_disabled(fake_st.calls) is True
    assert fake_st.session_state["error_message"] is None
    assert fake_st.session_state["error_source"] is None

def test_main_two_file_cooldown_blocks_before_pipeline_helper(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(
        button_clicked=True,
        input_mode="Two files",
        first_uploaded_file=FakeUploadedFile("orders.csv", b"x\n"),
        second_uploaded_file=FakeUploadedFile("products.csv", b"x\n"),
        first_logical_name="orders",
        second_logical_name="products",
        task_text="Merge files.",
    )
    fake_st.session_state["run_count"] = 1
    fake_st.session_state["last_run_timestamp"] = 100.0
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 102.0)
    monkeypatch.setattr(
        web,
        "run_uploaded_tasks_many",
        lambda **kwargs: calls.append(kwargs),
    )

    web.main()

    assert calls == []
    assert fake_st.session_state["error_message"] == (
        "Please wait 3.0s before running again."
    )

def test_main_generate_click_increments_run_count_before_pipeline(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    fake_st.session_state["run_count"] = 2
    fake_st.session_state["last_run_timestamp"] = 10.0
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 20.0)

    def fake_run_uploaded_task(
        _file_bytes: bytes,
        _suffix: str,
        _task_text: str,
        uploaded_file_name: str | None = None,
        audit_metadata: dict[str, object] | None = None,
    ) -> tuple[web.ExecutionResult, bytes, str]:
        assert fake_st.session_state["run_count"] == 3
        assert fake_st.session_state["last_run_timestamp"] == 20.0
        assert fake_st.session_state["is_running"] is True
        return (
            web.ExecutionResult(success=True),
            b"order_id,total\n1,10\n",
            web.derive_output_file_name(uploaded_file_name, ".csv"),
        )

    monkeypatch.setattr(web, "run_uploaded_task", fake_run_uploaded_task)

    web.main()

    assert fake_st.session_state["run_count"] == 3
    assert fake_st.session_state["last_run_timestamp"] == 20.0

def test_main_generate_click_updates_last_run_timestamp(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 42.0)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda _file_bytes, _suffix, _task_text, uploaded_file_name=None, audit_metadata=None: (
            web.ExecutionResult(success=True),
            b"order_id,total\n1,10\n",
            web.derive_output_file_name(uploaded_file_name, ".csv"),
        ),
    )

    web.main()

    assert fake_st.session_state["run_count"] == 1
    assert fake_st.session_state["last_run_timestamp"] == 42.0

def test_main_cooldown_blocked_generate_does_not_call_pipeline(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    fake_st.session_state["run_count"] = 1
    fake_st.session_state["last_run_timestamp"] = 100.0
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 102.0)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda *_args, **_kwargs: calls.append((_args, _kwargs)),
    )

    web.main()

    assert calls == []
    assert fake_st.session_state["run_count"] == 1
    assert fake_st.session_state["last_run_timestamp"] == 100.0
    assert fake_st.session_state["error_message"] == (
        "Please wait 3.0s before running again."
    )

def test_main_limit_blocked_generate_does_not_call_pipeline(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    fake_st.session_state["run_count"] = web.MAX_RUNS_PER_SESSION
    fake_st.session_state["last_run_timestamp"] = 100.0
    calls: list[object] = []
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(web.time, "monotonic", lambda: 120.0)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda *_args, **_kwargs: calls.append((_args, _kwargs)),
    )

    web.main()

    assert calls == []
    assert fake_st.session_state["run_count"] == web.MAX_RUNS_PER_SESSION
    assert fake_st.session_state["last_run_timestamp"] == 100.0
    assert fake_st.session_state["error_message"] == (
        "Run limit reached for this session."
    )

def test_main_success_stores_preview_and_renders_download(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    output_bytes = b"order_id,total\n1,10\n"
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    fake_st.session_state["error_message"] = "old error"
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda _file_bytes, _suffix, _task_text, uploaded_file_name=None, audit_metadata=None: (
            web.ExecutionResult(success=True),
            output_bytes,
            web.derive_output_file_name(uploaded_file_name, ".csv"),
        ),
    )

    web.main()

    assert isinstance(fake_st.session_state["result_preview"], pd.DataFrame)
    assert fake_st.session_state["output_bytes"] == output_bytes
    assert fake_st.session_state["output_file_name"] == (
        "orders_snapscript_output.csv"
    )
    assert fake_st.session_state["error_message"] is None
    assert fake_st.session_state["is_running"] is False
    assert any(name == "dataframe" for name, _args, _kwargs in fake_st.calls)
    download_calls = [
        kwargs for name, _args, kwargs in fake_st.calls if name == "download_button"
    ]
    assert download_calls == [
        {
            "label": "Download output",
            "data": output_bytes,
            "file_name": "orders_snapscript_output.csv",
            "mime": "text/csv",
        }
    ]

def test_main_failed_generate_clears_preview_and_hides_download(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text="Keep rows.",
    )
    fake_st.session_state.update(
        {
            "result_preview": pd.DataFrame({"old": [1]}),
            "output_bytes": b"old",
            "output_file_name": "old.csv",
        }
    )
    monkeypatch.setattr(web, "st", fake_st)
    monkeypatch.setattr(
        web,
        "run_uploaded_task",
        lambda _file_bytes, _suffix, _task_text, uploaded_file_name=None, audit_metadata=None: (
            web.ExecutionResult(
                success=False,
                stderr="RuntimeError: transform failed",
                exit_code=1,
            ),
            None,
            None,
        ),
    )

    web.main()

    assert fake_st.session_state["result_preview"] is None
    assert fake_st.session_state["output_bytes"] is None
    assert fake_st.session_state["output_file_name"] is None
    assert fake_st.session_state["error_message"] == (
        "Execution failed in the sandbox. Summary: "
        "RuntimeError: transform failed"
    )
    assert not any(name == "download_button" for name, _args, _kwargs in fake_st.calls)
