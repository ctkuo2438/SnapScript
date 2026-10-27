"""Synthetic uploads and public provider doubles for web behavior tests."""
import json
from streamlit.testing.v1 import AppTest

from snapscript.core.models import ProviderCallMetrics
from snapscript.interfaces import web_inputs, web_state


INPUT_BYTES = b"order_id,amount\n1,10\n2,20\n"
TASK = "Keep rows where amount is greater than 10."
COPY_CODE = """from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd
pd.read_csv(INPUT_PATH).to_csv(OUTPUT_PATH, index=False)
"""
METRICS = ProviderCallMetrics("fixture-provider", "fixture-model", 10, 5, 2)


def uploaded_state(two_files=False):
    state = {}
    web_state.initialize_session_state(state)
    if two_files:
        state.update(input_mode=web_state.INPUT_MODE_TWO, first_logical_name="orders", second_logical_name="products")
        for prefix in ("first", "second"):
            web_inputs.store_named_uploaded_file(state, prefix, f"{prefix}.csv", INPUT_BYTES)
    else:
        web_inputs.store_uploaded_file(state, "orders.csv", INPUT_BYTES)
    state["task_text"] = TASK
    return state


def uploaded_app(two_files=False, *, first_bytes=INPUT_BYTES, second_bytes=INPUT_BYTES, task=TASK):
    app = AppTest.from_file("app.py", default_timeout=10).run()
    if two_files:
        app.radio[0].set_value("Two files").run()
        app.text_input[0].set_value("orders")
        app.text_input[1].set_value("products")
        app.file_uploader[1].set_value(("products.csv", second_bytes, "text/csv"))
    app.file_uploader[0].set_value(("orders.csv", first_bytes, "text/csv"))
    app.text_area[0].set_value(task).run()
    assert not app.exception
    return app


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception


def audit_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
