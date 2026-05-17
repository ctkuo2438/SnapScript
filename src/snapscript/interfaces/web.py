from __future__ import annotations

from collections.abc import MutableMapping

import streamlit as st


MAX_RUNS_PER_SESSION = 10

SESSION_DEFAULTS: dict[str, object] = {
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


def initialize_session_state(
    state: MutableMapping[str, object] | None = None,
) -> None:
    target = st.session_state if state is None else state
    for key, default in SESSION_DEFAULTS.items():
        target.setdefault(key, default)


def get_remaining_runs(
    run_count: int,
    max_runs: int = MAX_RUNS_PER_SESSION,
) -> int:
    return max(0, max_runs - run_count)


def main() -> None:
    initialize_session_state()

    st.title("SnapScript")
    st.write("Transform a CSV or Excel file with a natural-language task.")

    st.file_uploader(
        "Upload CSV or Excel file",
        type=["csv", "xlsx", "xls"],
    )
    task_text = st.text_area(
        "Describe the transformation",
        value=str(st.session_state["task_text"]),
    )
    st.session_state["task_text"] = task_text

    remaining_runs = get_remaining_runs(int(st.session_state["run_count"]))
    st.caption(f"Remaining runs this session: {remaining_runs}")

    if st.button("Generate", disabled=remaining_runs == 0):
        st.info("Generation is not wired yet. This is the Phase 2 skeleton.")

    st.subheader("Output")
    st.info("Output preview will appear here after generation is wired.")

    st.subheader("Errors")
    error_message = st.session_state["error_message"]
    if error_message:
        st.error(str(error_message))
    else:
        st.info("No errors.")
