'''
Streamlit session-state helpers.
'''

from __future__ import annotations
from typing import cast

from collections.abc import MutableMapping


MAX_RUNS_PER_SESSION = 10
COOLDOWN_SECONDS = 5
MAX_REWRITES_PER_SESSION = 10
REWRITE_COOLDOWN_SECONDS = 3
INPUT_MODE_SINGLE = "Single file"
INPUT_MODE_TWO = "Two files"
ERROR_SOURCE_UPLOAD = "upload"
ERROR_SOURCE_VALIDATION = "validation"
ERROR_SOURCE_EXECUTION = "execution"

SESSION_DEFAULTS: dict[str, object] = {
    "input_mode": INPUT_MODE_SINGLE,
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


def initialize_session_state(state: MutableMapping[str, object]) -> None:
    for key, default in SESSION_DEFAULTS.items():
        state.setdefault(key, default)


def clear_output_state(state: MutableMapping[str, object]) -> None:
    state["result_preview"] = None
    state["output_bytes"] = None
    state["output_file_name"] = None


def begin_accepted_run(state: MutableMapping[str, object], now: float | None = None) -> None:
    state["error_message"] = None
    state["error_source"] = None
    clear_output_state(state)
    state["is_running"] = True
    if now is not None:
        state["run_count"] = cast(int, state.get("run_count", 0)) + 1
        state["last_run_timestamp"] = now


def mark_run_success(
    state: MutableMapping[str, object],
    preview: object,
    output_bytes: bytes,
    output_file_name: str,
) -> None:
    state["result_preview"] = preview
    state["output_bytes"] = output_bytes
    state["output_file_name"] = output_file_name
    state["error_message"] = None
    state["error_source"] = None
    state["is_running"] = False


def mark_run_failure(state: MutableMapping[str, object], error_message: str) -> None:
    clear_output_state(state)
    state["error_message"] = error_message
    state["error_source"] = ERROR_SOURCE_EXECUTION
    state["is_running"] = False


def mark_validation_error(state: MutableMapping[str, object], error_message: str) -> None:
    state["error_message"] = error_message
    state["error_source"] = ERROR_SOURCE_VALIDATION
    state["is_running"] = False


def get_remaining_runs(
    run_count: int,
    max_runs: int = MAX_RUNS_PER_SESSION,
) -> int:
    return max(0, max_runs - run_count)


def check_rate_limit(
    run_count: int,
    last_run_timestamp: float | None,
    now: float,
    max_runs: int = MAX_RUNS_PER_SESSION,
    cooldown_seconds: int = COOLDOWN_SECONDS,
) -> tuple[bool, str | None]:
    if run_count >= max_runs:
        return False, "Run limit reached for this session."

    if last_run_timestamp is not None:
        elapsed = now - last_run_timestamp
        remaining = cooldown_seconds - elapsed
        if remaining > 0:
            return False, f"Please wait {remaining:.1f}s before running again."

    return True, None


def get_remaining_rewrites(rewrite_count: int, max_rewrites: int = MAX_REWRITES_PER_SESSION) -> int:
    return max(0, max_rewrites - rewrite_count)


def check_rewrite_rate_limit(
    rewrite_count: int,
    last_rewrite_timestamp: float | None,
    now: float,
    max_rewrites: int = MAX_REWRITES_PER_SESSION,
    cooldown_seconds: int = REWRITE_COOLDOWN_SECONDS,
) -> tuple[bool, str | None]:
    if rewrite_count >= max_rewrites:
        return False, "Rewrite limit reached for this session."

    if last_rewrite_timestamp is not None:
        elapsed = now - last_rewrite_timestamp
        remaining = cooldown_seconds - elapsed
        if remaining > 0:
            return (
                False,
                f"Please wait {remaining:.1f}s before improving the task again.",
            )

    return True, None


def begin_accepted_rewrite(state: MutableMapping[str, object], now: float) -> None:
    state["rewrite_error_message"] = None
    state["rewrite_count"] = cast(int, state.get("rewrite_count", 0)) + 1
    state["last_rewrite_timestamp"] = now
    state["is_rewriting_task"] = True
