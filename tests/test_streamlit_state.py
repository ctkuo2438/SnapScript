import pandas as pd
import pytest

from snapscript.interfaces import web, web_assistant, web_state
from helpers.web_helpers import uploaded_state


EXPECTED_SESSION_DEFAULTS = {
    "input_mode": "Single file",
    "uploaded_file_name": None,
    "uploaded_file_bytes": None,
    "uploaded_file_suffix": None,
    "first_uploaded_file_name": None,
    "first_uploaded_file_bytes": None,
    "first_uploaded_file_suffix": None,
    "second_uploaded_file_name": None,
    "second_uploaded_file_bytes": None,
    "second_uploaded_file_suffix": None,
    "first_logical_name": "",
    "second_logical_name": "",
    "task_text": "",
    "result_preview": None,
    "output_bytes": None,
    "output_file_name": None,
    "error_message": None,
    "error_source": None,
    "rewritten_task": None,
    "rewrite_error_message": None,
    "is_rewriting_task": False,
    "rewrite_count": 0,
    "last_rewrite_timestamp": None,
    "run_count": 0,
    "last_run_timestamp": None,
    "is_running": False,
}


def test_initialize_session_state_sets_expected_defaults() -> None:
    state: dict[str, object] = {"run_count": 3}

    web.initialize_session_state(state)

    assert state["run_count"] == 3
    for key, expected in EXPECTED_SESSION_DEFAULTS.items():
        assert key in state
        if key != "run_count":
            assert state[key] == expected


@pytest.mark.parametrize("change", [
    {"task_text": "Another task"}, {"uploaded_file_bytes": b"changed"},
    {"input_mode": "Two files"}, {"first_logical_name": "sales"},
])
def test_changed_input_invalidates_output_rewrite_and_only_relevant_cache(change):
    state = uploaded_state()
    cache = object()
    state.update(output_bytes=b"old", output_file_name="old.csv", result_preview="old",
                 rewritten_task="old rewrite", rewrite_error_message="old rewrite error",
                 error_source="execution", error_message="old execution error", _schema_cache=cache)

    web_state.update_input_state(state, **change)

    assert all(state[key] is None for key in (
        "output_bytes", "output_file_name", "result_preview", "rewritten_task",
        "rewrite_error_message", "error_message", "error_source",
    ))
    assert (state.get("_schema_cache") is cache) is (set(change) == {"task_text"})


@pytest.mark.parametrize("source", ["upload", "validation", "execution"])
def test_unchanged_input_preserves_output_errors_and_schema_cache(source):
    state = uploaded_state()
    state.update(output_bytes=b"old", output_file_name="old.csv", result_preview="old",
                 rewritten_task="old rewrite", error_message="old error", error_source=source,
                 _schema_cache=object())
    before = dict(state)

    web_state.update_input_state(state, task_text=state["task_text"])

    assert state == before


@pytest.mark.parametrize("source", ["upload", "validation"])
def test_task_edits_do_not_clear_other_input_errors(source):
    state = uploaded_state()
    state.update(error_source=source, error_message="input error")
    web_state.update_input_state(state, task_text="Edited task")
    assert (state["error_source"], state["error_message"]) == (source, "input error")

def test_session_defaults_exactly_match_phase_2_plan_keys() -> None:
    assert set(web_state.SESSION_DEFAULTS) == set(EXPECTED_SESSION_DEFAULTS)

def test_clear_output_state_only_clears_output_fields() -> None:
    state: dict[str, object] = {
        "uploaded_file_name": "orders.csv",
        "uploaded_file_bytes": b"input",
        "uploaded_file_suffix": ".csv",
        "task_text": "Keep rows.",
        "result_preview": pd.DataFrame({"old": [1]}),
        "output_bytes": b"old",
        "output_file_name": "old.csv",
        "error_message": "old error",
        "run_count": 4,
        "last_run_timestamp": 123.0,
        "is_running": True,
    }

    web_state.clear_output_state(state)

    assert state["result_preview"] is None
    assert state["output_bytes"] is None
    assert state["output_file_name"] is None
    assert state["uploaded_file_name"] == "orders.csv"
    assert state["uploaded_file_bytes"] == b"input"
    assert state["uploaded_file_suffix"] == ".csv"
    assert state["task_text"] == "Keep rows."
    assert state["error_message"] == "old error"
    assert state["run_count"] == 4
    assert state["last_run_timestamp"] == 123.0
    assert state["is_running"] is True

def test_begin_accepted_run_clears_error_and_output_state() -> None:
    state: dict[str, object] = {
        "result_preview": pd.DataFrame({"old": [1]}),
        "output_bytes": b"old",
        "output_file_name": "old.csv",
        "error_message": "old error",
        "run_count": 2,
        "last_run_timestamp": 123.0,
        "is_running": False,
    }

    web.begin_accepted_run(state)

    assert state["result_preview"] is None
    assert state["output_bytes"] is None
    assert state["output_file_name"] is None
    assert state["error_message"] is None
    assert state["is_running"] is True
    assert state["run_count"] == 2
    assert state["last_run_timestamp"] == 123.0

def test_begin_accepted_run_with_timestamp_increments_run_count() -> None:
    state: dict[str, object] = {
        "result_preview": pd.DataFrame({"old": [1]}),
        "output_bytes": b"old",
        "output_file_name": "old.csv",
        "error_message": "old error",
        "run_count": 2,
        "last_run_timestamp": 123.0,
        "is_running": False,
    }

    web.begin_accepted_run(state, now=200.0)

    assert state["result_preview"] is None
    assert state["output_bytes"] is None
    assert state["output_file_name"] is None
    assert state["error_message"] is None
    assert state["is_running"] is True
    assert state["run_count"] == 3
    assert state["last_run_timestamp"] == 200.0

def test_mark_run_success_stores_output_and_clears_error() -> None:
    preview = pd.DataFrame({"order_id": [1]})
    state: dict[str, object] = {
        "result_preview": None,
        "output_bytes": None,
        "output_file_name": None,
        "error_message": "old error",
        "is_running": True,
    }

    web.mark_run_success(
        state,
        preview,
        b"order_id\n1\n",
        "orders_snapscript_output.csv",
    )

    assert state["result_preview"] is preview
    assert state["output_bytes"] == b"order_id\n1\n"
    assert state["output_file_name"] == "orders_snapscript_output.csv"
    assert state["error_message"] is None
    assert state["is_running"] is False

def test_mark_run_failure_clears_stale_output_and_stores_error() -> None:
    state: dict[str, object] = {
        "result_preview": pd.DataFrame({"old": [1]}),
        "output_bytes": b"old",
        "output_file_name": "old.csv",
        "error_message": None,
        "is_running": True,
    }

    web.mark_run_failure(state, "Execution failed")

    assert state["result_preview"] is None
    assert state["output_bytes"] is None
    assert state["output_file_name"] is None
    assert state["error_message"] == "Execution failed"
    assert state["is_running"] is False

def test_mark_validation_error_preserves_existing_output() -> None:
    preview = pd.DataFrame({"old": [1]})
    state: dict[str, object] = {
        "result_preview": preview,
        "output_bytes": b"old",
        "output_file_name": "old.csv",
        "error_message": None,
        "is_running": True,
    }

    web.mark_validation_error(state, "Task description is required.")

    assert state["result_preview"] is preview
    assert state["output_bytes"] == b"old"
    assert state["output_file_name"] == "old.csv"
    assert state["error_message"] == "Task description is required."
    assert state["is_running"] is False

def test_get_remaining_runs_never_returns_negative() -> None:
    assert web.get_remaining_runs(0) == 10
    assert web.get_remaining_runs(7) == 3
    assert web.get_remaining_runs(10) == 0
    assert web.get_remaining_runs(12) == 0
    assert web.get_remaining_runs(2, max_runs=4) == 2

def test_check_rate_limit_accepts_when_under_limit_without_recent_run() -> None:
    accepted, message = web.check_rate_limit(
        run_count=2,
        last_run_timestamp=None,
        now=100.0,
    )

    assert accepted is True
    assert message is None

def test_check_rate_limit_blocks_when_run_limit_reached() -> None:
    accepted, message = web.check_rate_limit(
        run_count=web.MAX_RUNS_PER_SESSION,
        last_run_timestamp=None,
        now=100.0,
    )

    assert accepted is False
    assert message == "Run limit reached for this session."

def test_check_rate_limit_blocks_when_cooldown_is_active() -> None:
    accepted, message = web.check_rate_limit(
        run_count=2,
        last_run_timestamp=100.0,
        now=102.25,
    )

    assert accepted is False
    assert message == "Please wait 2.8s before running again."

def test_check_rate_limit_accepts_when_cooldown_has_elapsed() -> None:
    accepted, message = web.check_rate_limit(
        run_count=2,
        last_run_timestamp=100.0,
        now=105.0,
    )

    assert accepted is True
    assert message is None

def test_get_remaining_rewrites_never_returns_negative() -> None:
    assert web_state.get_remaining_rewrites(0) == 10
    assert web_state.get_remaining_rewrites(7) == 3
    assert web_state.get_remaining_rewrites(10) == 0
    assert web_state.get_remaining_rewrites(12) == 0
    assert web_state.get_remaining_rewrites(2, max_rewrites=4) == 2

def test_check_rewrite_rate_limit_accepts_without_recent_rewrite() -> None:
    accepted, message = web_state.check_rewrite_rate_limit(
        rewrite_count=2,
        last_rewrite_timestamp=None,
        now=100.0,
    )

    assert accepted is True
    assert message is None

def test_check_rewrite_rate_limit_blocks_when_limit_reached() -> None:
    accepted, message = web_state.check_rewrite_rate_limit(
        rewrite_count=web_assistant.MAX_REWRITES_PER_SESSION,
        last_rewrite_timestamp=None,
        now=100.0,
    )

    assert accepted is False
    assert message == "Rewrite limit reached for this session."

def test_check_rewrite_rate_limit_blocks_during_cooldown() -> None:
    accepted, message = web_state.check_rewrite_rate_limit(
        rewrite_count=2,
        last_rewrite_timestamp=100.0,
        now=101.25,
    )

    assert accepted is False
    assert message == "Please wait 1.8s before improving the task again."

def test_check_rewrite_rate_limit_accepts_after_cooldown() -> None:
    accepted, message = web_state.check_rewrite_rate_limit(
        rewrite_count=2,
        last_rewrite_timestamp=100.0,
        now=103.0,
    )

    assert accepted is True
    assert message is None

def test_begin_accepted_rewrite_increments_without_clearing_output() -> None:
    preview = pd.DataFrame({"old": [1]})
    state: dict[str, object] = {
        "rewrite_error_message": "old error",
        "rewrite_count": 2,
        "last_rewrite_timestamp": 10.0,
        "is_rewriting_task": False,
        "result_preview": preview,
        "output_bytes": b"old",
        "output_file_name": "old.csv",
    }

    web_state.begin_accepted_rewrite(state, now=20.0)

    assert state["rewrite_error_message"] is None
    assert state["rewrite_count"] == 3
    assert state["last_rewrite_timestamp"] == 20.0
    assert state["is_rewriting_task"] is True
    assert state["result_preview"] is preview
    assert state["output_bytes"] == b"old"
    assert state["output_file_name"] == "old.csv"
