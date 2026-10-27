"""Prompt coach presentation and validation without a full fake Streamlit app."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from helpers.web_helpers import uploaded_state
from snapscript.config import AppConfig
from snapscript.core.models import TaskAdvice
from snapscript.interfaces import web_assistant


@pytest.mark.parametrize("quality,method,label", [
    ("good", "success", "Good"), ("too_vague", "warning", "Too Vague"),
    ("needs_detail", "info", "Needs Detail"),
])
@pytest.mark.parametrize("two_files", [False, True])
def test_coach_displays_advice_without_changing_task_or_output(monkeypatch, two_files, quality, method, label):
    state = uploaded_state(two_files)
    state.update(output_bytes=b"old", output_file_name="old.csv", result_preview="old", run_count=3)
    before = dict(state)
    ui = SimpleNamespace(**{name: Mock() for name in ("subheader", "write", "success", "warning", "info")})
    monkeypatch.setattr(web_assistant, "st", ui)
    advice = TaskAdvice(quality, ["key columns"], ["State the desired columns."], "Do not auto-apply this.")
    monkeypatch.setattr(web_assistant.task_advisor, "advise_task", Mock(return_value=advice))

    web_assistant.render_prompt_coach(state, AppConfig())

    getattr(ui, method).assert_called_once_with(f"Status: {label}")
    rendered = " ".join(str(call) for call in ui.write.call_args_list)
    assert "key columns" in rendered
    assert "State the desired columns." in rendered
    assert "Do not auto-apply this" not in rendered
    assert "Guidance:" not in rendered
    assert all(state[key] == value for key, value in before.items())


@pytest.mark.parametrize("reason", ["blank", "missing", "invalid"])
def test_coach_skips_empty_or_unreadable_context(monkeypatch, reason):
    state = uploaded_state()
    if reason == "blank":
        state["task_text"] = " "
    elif reason == "missing":
        state["uploaded_file_bytes"] = None
    else:
        state["uploaded_file_bytes"] = b""
    ui = SimpleNamespace(subheader=Mock())
    monkeypatch.setattr(web_assistant, "st", ui)

    web_assistant.render_prompt_coach(state, AppConfig())

    ui.subheader.assert_not_called()
