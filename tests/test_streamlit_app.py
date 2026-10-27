from io import BytesIO

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from snapscript.core.models import GeneratedScript
from snapscript.core.provider import ProviderCallError
from snapscript.interfaces import errors, web, web_pipeline
from helpers.web_helpers import INPUT_BYTES, TASK, audit_events, click, uploaded_app


SINGLE_CODE = """from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd
orders = pd.read_csv(INPUT_PATH)
orders[orders['amount'] > 1000].to_csv(OUTPUT_PATH, index=False)
"""
MULTI_CODE = """from _snapscript_paths import INPUT_PATHS, OUTPUT_PATH
import pandas as pd
orders = pd.read_csv(INPUT_PATHS['orders'])
products = pd.read_csv(INPUT_PATHS['products'])
orders.merge(products, on='pid', how='inner').to_csv(OUTPUT_PATH, index=False)
"""


@pytest.mark.parametrize(
    ("two_files", "code", "expected"),
    [
        (False, SINGLE_CODE, {"pid": ["p2"], "amount": [2000]}),
        (
            True,
            MULTI_CODE,
            {"pid": ["p1", "p2"], "amount": [100, 2000], "name": ["A", "B"]},
        ),
    ],
)
def test_app_upload_generate_and_download(web_runtime, two_files, code, expected):
    generate = web_runtime.generate
    generate.return_value = GeneratedScript(code=code, raw_response=code, model="fixture")
    app = uploaded_app(
        two_files, first_bytes=b"pid,amount\np1,100\np2,2000\n",
        second_bytes=b"pid,name\np1,A\np2,B\n",
        task="Merge orders and products on pid." if two_files else "Keep rows where amount > 1000.",
    )
    observed_budgets = []

    def record_generation(*args, **kwargs):
        observed_budgets.append((app.session_state["run_count"], app.session_state["rewrite_count"]))
        return generate.return_value

    generate.side_effect = record_generation
    app.session_state["rewrite_count"] = 10
    app.run()
    assert not app.exception
    generate.assert_not_called()

    click(app, "Generate")

    generate.assert_called_once()
    assert observed_budgets == [(1, 10)]
    assert app.session_state["run_count"] == 1
    assert app.session_state["last_run_timestamp"] is not None
    assert app.session_state["error_message"] is None
    output = pd.read_csv(BytesIO(app.session_state["output_bytes"]))
    pd.testing.assert_frame_equal(output, pd.DataFrame(expected))
    assert len(app.get("download_button")) == 1
    event, = audit_events(web_runtime.audit_path)
    assert event["success"] is True


@pytest.mark.parametrize("two_files", [False, True])
@pytest.mark.parametrize("outcome,category", [
    ("execution", "sandbox_failure"), ("provider", "provider_failure"),
    ("missing", "unknown_failure"), ("preview", "output_validation"),
    ("exception", "unknown_failure"),
])
def test_failed_generate_hides_stale_download_and_writes_one_safe_event(monkeypatch, web_runtime, two_files, outcome, category):
    app = uploaded_app(two_files)
    app.session_state["output_bytes"] = b"old output"
    app.session_state["output_file_name"] = "old.csv"
    app.session_state["result_preview"] = pd.DataFrame({"old": [1]})
    diagnostic = "Traceback (most recent call last):\n  File '/tmp/private.py'\nValueError: token=fixture-secret " + "x" * 1000

    def fail(*args, audit_metadata=None, **kwargs):
        audit_metadata["provider_called"] = True
        if outcome == "provider":
            raise ProviderCallError(diagnostic)
        if outcome == "exception":
            raise RuntimeError(diagnostic)
        if outcome == "execution":
            return web.ExecutionResult(False, stderr=diagnostic, error_category="sandbox_failure"), None, None
        return web.ExecutionResult(True), (b"" if outcome == "preview" else None), "out.csv"

    for name in ("run_uploaded_task", "run_uploaded_tasks_many"):
        monkeypatch.setattr(web_pipeline, name, fail)
    monkeypatch.setattr(errors, "ERROR_MAX_CHARS", 120)
    click(app, "Generate")

    assert (app.session_state["run_count"], app.session_state["rewrite_count"]) == (1, 0)
    assert all(app.session_state[key] is None for key in ("output_bytes", "output_file_name", "result_preview"))
    assert not app.get("download_button")
    assert app.error
    message = app.session_state["error_message"]
    assert app.session_state["error_source"] == "execution"
    assert len(message) <= 120
    assert not any(value in message for value in ("fixture-secret", "Traceback", "/tmp/private"))
    event, = audit_events(web_runtime.audit_path)
    assert event["success"] is False and event["error_category"] == category
    assert event["provider_called"] is True
    assert event["output_file_sha256"] is None
    assert "fixture-secret" not in web_runtime.audit_path.read_text()
    app.run()
    assert app.session_state["error_message"] == message
    assert len(audit_events(web_runtime.audit_path)) == 1
    app.text_area[0].set_value("Keep all rows after correcting the task.").run()
    assert not app.exception
    assert app.session_state["error_message"] is None
    assert app.session_state["error_source"] is None
    assert not app.error
    assert app.session_state["run_count"] == 1
    assert len(audit_events(web_runtime.audit_path)) == 1


def test_switching_to_single_file_clears_stale_two_file_validation(web_runtime):
    app = AppTest.from_file("app.py", default_timeout=10).run()
    app.radio[0].set_value("Two files").run()
    app.text_input[0].set_value("orders")
    app.text_input[1].set_value("products")
    app.text_area[0].set_value(TASK).run()
    assert not app.exception
    assert app.session_state["error_source"] == "validation"
    assert app.error

    app.radio[0].set_value("Single file").run()

    assert not app.exception
    assert app.session_state["input_mode"] == "Single file"
    assert app.session_state["error_message"] is None
    assert app.session_state["error_source"] is None
    assert not app.error
    assert (app.session_state["run_count"], app.session_state["rewrite_count"]) == (0, 0)
    web_runtime.generate.assert_not_called()
    web_runtime.rewrite.assert_not_called()
    assert not audit_events(web_runtime.audit_path)


@pytest.mark.parametrize("reason,disabled", [("missing_upload", True), ("blank_task", True), ("quota", True), ("ready", False)])
def test_rewrite_button_disabled_state_matches_input_and_quota(web_runtime, reason, disabled):
    app = AppTest.from_file("app.py", default_timeout=10).run()
    if reason != "missing_upload":
        app.file_uploader[0].set_value(("orders.csv", INPUT_BYTES, "text/csv"))
    if reason != "blank_task":
        app.text_area[0].set_value(TASK)
    if reason == "quota":
        app.session_state["rewrite_count"] = 10

    app.run()

    assert not app.exception
    button = next(button for button in app.button if button.label == "Improve task with AI")
    assert button.disabled is disabled
    web_runtime.generate.assert_not_called()
    web_runtime.rewrite.assert_not_called()
    assert not audit_events(web_runtime.audit_path)


@pytest.mark.parametrize("two_files", [False, True])
def test_rewrite_is_explicit_preserves_output_until_applied(web_runtime, two_files):
    app = uploaded_app(two_files)
    original_task = app.text_area[0].value
    app.session_state["output_bytes"] = b"old output"
    app.session_state["output_file_name"] = "old.csv"
    app.session_state["result_preview"] = pd.DataFrame({"old": [1]})
    app.session_state["run_count"] = 10
    app.run()
    web_runtime.generate.assert_not_called()
    web_runtime.rewrite.assert_not_called()
    assert not audit_events(web_runtime.audit_path)

    click(app, "Improve task with AI")

    web_runtime.rewrite.assert_called_once()
    assert (app.session_state["rewrite_count"], app.session_state["run_count"]) == (1, 10)
    assert app.session_state["output_bytes"] == b"old output"
    assert app.get("download_button")
    assert len(audit_events(web_runtime.audit_path)) == 1
    app.run()  # Ignoring the proposed rewrite does not apply or repeat it.
    assert app.text_area[0].value == original_task
    assert app.session_state["output_bytes"] == b"old output"
    click(app, "Use rewritten task")
    assert app.text_area[0].value == web_runtime.rewrite.return_value.rewritten_task
    assert app.session_state["output_bytes"] is None
    assert not app.get("download_button")
    web_runtime.generate.assert_not_called()
    web_runtime.rewrite.assert_called_once()


def test_rewrite_failure_is_visible_redacted_and_consumes_one_attempt(web_runtime):
    app = uploaded_app()
    web_runtime.rewrite.side_effect = ProviderCallError("token=fixture-secret")

    click(app, "Improve task with AI")

    assert app.session_state["rewrite_count"] == 1
    assert app.session_state["run_count"] == 0
    assert app.error
    assert all("fixture-secret" not in item.value and "Traceback" not in item.value for item in app.error)
    assert app.session_state["rewritten_task"] is None
    assert len(audit_events(web_runtime.audit_path)) == 1
    web_runtime.generate.assert_not_called()


def test_oversized_upload_is_rejected_and_a_valid_replacement_clears_the_error(web_runtime):
    from snapscript.interfaces.web_inputs import MAX_UPLOAD_BYTES

    app = AppTest.from_file("app.py", default_timeout=10).run()
    app.file_uploader[0].set_value(("large.csv", b"x" * (MAX_UPLOAD_BYTES + 1), "text/csv")).run()

    assert not app.exception
    assert app.error and "10 MB" in app.error[0].value
    assert app.session_state["uploaded_file_bytes"] is None
    assert next(button for button in app.button if button.label == "Generate").disabled
    assert app.session_state["run_count"] == 0
    assert not audit_events(web_runtime.audit_path)

    app.file_uploader[0].set_value(("valid.csv", INPUT_BYTES, "text/csv")).run()

    assert not app.exception
    assert app.session_state["uploaded_file_bytes"] == INPUT_BYTES
    assert app.session_state["error_message"] is None
    web_runtime.generate.assert_not_called()
    web_runtime.rewrite.assert_not_called()


@pytest.mark.parametrize(("variable", "value", "expected"), [
    ("SNAPSCRIPT_DOCKER_TIMEOUT_SECONDS", "120", "docker_timeout_seconds must be at most 30"),
    ("SNAPSCRIPT_SANDBOX_BACKEND", "podman", "SNAPSCRIPT_SANDBOX_BACKEND must be one of"),
])
def test_app_reports_invalid_configuration_without_exception_page(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str, expected: str,
) -> None:
    monkeypatch.setenv(variable, value)

    app = AppTest.from_file("app.py", default_timeout=10).run()

    assert not app.exception
    assert len(app.error) == 1
    assert expected in app.error[0].value
    assert "Traceback" not in app.error[0].value
    assert not app.button
