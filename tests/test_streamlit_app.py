import ast
import re
from pathlib import Path

import pytest

from snapscript.interfaces import web


EXPECTED_SESSION_DEFAULTS = {
    "uploaded_file_name": None,
    "uploaded_file_bytes": None,
    "uploaded_file_suffix": None,
    "task_text": "",
    "result_preview": None,
    "output_bytes": None,
    "output_file_name": None,
    "error_message": None,
    "run_count": 0,
    "last_run_timestamp": None,
    "is_running": False,
}


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
    ) -> None:
        self.session_state: dict[str, object] = {}
        self.calls: list[
            tuple[str, tuple[object, ...], dict[str, object]]
        ] = []
        self.button_clicked = button_clicked
        self.uploaded_file = uploaded_file
        self.task_text = task_text

    def title(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("title", args, kwargs))

    def write(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("write", args, kwargs))

    def file_uploader(
        self, *args: object, **kwargs: object
    ) -> FakeUploadedFile | None:
        self.calls.append(("file_uploader", args, kwargs))
        return self.uploaded_file

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


def _button_disabled(
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]],
) -> bool:
    button_calls = [kwargs for name, _args, kwargs in calls if name == "button"]
    assert len(button_calls) == 1
    return bool(button_calls[0].get("disabled", False))


def _has_placeholder_message(
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]],
) -> bool:
    return (
        "info",
        ("Generation is not wired yet. This is the Phase 2 skeleton.",),
        {},
    ) in calls


def test_app_entrypoint_only_delegates_to_web_main() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    ast.parse(source)

    assert source == (
        "from snapscript.interfaces.web import main\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    main()\n"
    )


def test_initialize_session_state_sets_expected_defaults() -> None:
    state: dict[str, object] = {"run_count": 3}

    web.initialize_session_state(state)

    assert state["run_count"] == 3
    for key, expected in EXPECTED_SESSION_DEFAULTS.items():
        assert key in state
        if key != "run_count":
            assert state[key] == expected


def test_get_remaining_runs_never_returns_negative() -> None:
    assert web.get_remaining_runs(0) == 10
    assert web.get_remaining_runs(7) == 3
    assert web.get_remaining_runs(10) == 0
    assert web.get_remaining_runs(12) == 0
    assert web.get_remaining_runs(2, max_runs=4) == 2


def test_normalize_task_text_strips_whitespace() -> None:
    assert web.normalize_task_text("  Keep large orders. \n") == (
        "Keep large orders."
    )


def test_validate_task_text_accepts_nonblank_text() -> None:
    assert web.validate_task_text("  Keep large orders. ") == (
        "Keep large orders."
    )


@pytest.mark.parametrize("task_text", ["", "   ", "\n\t"])
def test_validate_task_text_rejects_blank_text(task_text: str) -> None:
    with pytest.raises(ValueError, match="Task description is required"):
        web.validate_task_text(task_text)


def test_can_generate_rejects_missing_upload() -> None:
    can_run, message = web.can_generate(
        {
            "uploaded_file_bytes": None,
            "uploaded_file_suffix": None,
            "task_text": "Keep large orders.",
            "run_count": 0,
        }
    )

    assert can_run is False
    assert message == "Upload a CSV or Excel file before generating."


def test_can_generate_rejects_blank_task_text() -> None:
    can_run, message = web.can_generate(
        {
            "uploaded_file_bytes": b"order_id,total\n1,10\n",
            "uploaded_file_suffix": ".csv",
            "task_text": "   ",
            "run_count": 0,
        }
    )

    assert can_run is False
    assert message == "Task description is required."


def test_can_generate_rejects_run_limit() -> None:
    can_run, message = web.can_generate(
        {
            "uploaded_file_bytes": b"order_id,total\n1,10\n",
            "uploaded_file_suffix": ".csv",
            "task_text": "Keep large orders.",
            "run_count": web.MAX_RUNS_PER_SESSION,
        }
    )

    assert can_run is False
    assert message == "Run limit reached for this session."


def test_can_generate_accepts_valid_upload_and_task_text() -> None:
    can_run, message = web.can_generate(
        {
            "uploaded_file_bytes": b"order_id,total\n1,10\n",
            "uploaded_file_suffix": ".csv",
            "task_text": "Keep large orders.",
            "run_count": 0,
        }
    )

    assert can_run is True
    assert message is None


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("orders.csv", ".csv"),
        ("orders.xlsx", ".xlsx"),
        ("orders.xls", ".xls"),
        ("ORDERS.CSV", ".csv"),
    ],
)
def test_validate_upload_suffix_accepts_supported_suffixes(
    file_name: str,
    expected: str,
) -> None:
    assert web.validate_upload_suffix(file_name) == expected


def test_validate_upload_suffix_rejects_unsupported_suffix() -> None:
    with pytest.raises(ValueError, match="Unsupported file type"):
        web.validate_upload_suffix("orders.txt")


def test_validate_upload_size_rejects_large_upload() -> None:
    with pytest.raises(ValueError, match="10 MB"):
        web.validate_upload_size(web.MAX_UPLOAD_BYTES + 1)


def test_store_uploaded_file_sets_name_suffix_and_bytes() -> None:
    state: dict[str, object] = {"error_message": "old error"}
    file_bytes = b"order_id,total\n1,10\n"

    web.store_uploaded_file(state, "Orders.CSV", file_bytes)

    assert state["uploaded_file_name"] == "Orders.CSV"
    assert state["uploaded_file_suffix"] == ".csv"
    assert state["uploaded_file_bytes"] == file_bytes
    assert state["error_message"] is None


def test_store_uploaded_file_rejects_invalid_data_before_storing() -> None:
    state: dict[str, object] = {
        "uploaded_file_name": "previous.csv",
        "uploaded_file_suffix": ".csv",
        "uploaded_file_bytes": b"previous",
        "error_message": None,
    }

    with pytest.raises(ValueError, match="Unsupported file type"):
        web.store_uploaded_file(state, "orders.txt", b"not,csv\n")

    assert state["uploaded_file_name"] is None
    assert state["uploaded_file_suffix"] is None
    assert state["uploaded_file_bytes"] is None
    assert state["error_message"] == "Unsupported file type: .txt"


def test_write_upload_to_temp_input_uses_internal_filename(
    tmp_path: Path,
) -> None:
    file_bytes = b"order_id,total\n1,10\n"

    input_path = web.write_upload_to_temp_input(
        tmp_path,
        file_bytes,
        ".csv",
    )

    assert input_path == tmp_path / "input.csv"
    assert input_path.read_bytes() == file_bytes
    assert input_path.resolve().parent == tmp_path.resolve()


def test_path_like_upload_name_does_not_affect_temp_filename(
    tmp_path: Path,
) -> None:
    state: dict[str, object] = {}
    file_bytes = b"order_id,total\n1,10\n"
    web.store_uploaded_file(state, "../../secret.csv", file_bytes)

    input_path = web.write_upload_to_temp_input(
        tmp_path,
        bytes(state["uploaded_file_bytes"]),
        str(state["uploaded_file_suffix"]),
    )

    assert input_path == tmp_path / "input.csv"
    assert input_path.read_bytes() == file_bytes


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


def test_main_generate_click_validates_then_shows_placeholder(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(
        button_clicked=True,
        uploaded_file=uploaded,
        task_text=" Keep large orders. ",
    )
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert _button_disabled(fake_st.calls) is False
    assert fake_st.session_state["task_text"] == " Keep large orders. "
    assert fake_st.session_state["error_message"] is None
    assert _has_placeholder_message(fake_st.calls)


def test_uploading_file_alone_does_not_show_generation_placeholder(
    monkeypatch,
) -> None:
    uploaded = FakeUploadedFile("orders.csv", b"order_id,total\n1,10\n")
    fake_st = FakeStreamlit(uploaded_file=uploaded)
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert not _has_placeholder_message(fake_st.calls)


def test_editing_task_text_alone_does_not_show_generation_placeholder(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit(task_text="Keep large orders.")
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    assert fake_st.session_state["task_text"] == "Keep large orders."
    assert not _has_placeholder_message(fake_st.calls)


def test_main_renders_phase_2_skeleton_without_pipeline_calls(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(web, "st", fake_st)

    web.main()

    call_names = [name for name, _args, _kwargs in fake_st.calls]
    assert "title" in call_names
    assert "file_uploader" in call_names
    assert "text_area" in call_names
    assert "button" in call_names
    assert "caption" in call_names
    assert not _has_placeholder_message(fake_st.calls)


def test_web_imports_streamlit_but_not_provider_or_execution_pipeline() -> None:
    source = Path("src/snapscript/interfaces/web.py").read_text(encoding="utf-8")

    assert "import streamlit as st" in source
    assert "code_generator" not in source
    assert "retry_handler" not in source
    assert "safety_checker" not in source
    assert "sandbox_executor" not in source
    assert ".generate(" not in source
    assert ".execute(" not in source


def test_core_has_no_streamlit_or_web_ui_dependency() -> None:
    disallowed = ("streamlit", "gradio", "fastapi", "flask", "dash")

    for path in Path("src/snapscript/core").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for term in disallowed:
            assert term not in source, f"{term} found in {path}"
        assert re.search(r"\bst\.", source) is None, f"st. found in {path}"
