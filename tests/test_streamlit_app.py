from io import BytesIO
import json
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from snapscript.config import AppConfig
from snapscript.core import code_generator
from snapscript.core.models import GeneratedScript
from snapscript.interfaces import web


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
def test_app_upload_generate_and_download(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    two_files: bool,
    code: str,
    expected: dict[str, list[str] | list[int]],
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        web, "AppConfig", lambda: AppConfig(sandbox_backend="subprocess")
    )
    log_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(web, "AUDIT_LOG_PATH", log_path)
    generate = Mock(
        return_value=GeneratedScript(code=code, raw_response=code, model="fixture")
    )
    monkeypatch.setattr(code_generator, "generate", generate)
    app = AppTest.from_file("app.py", default_timeout=10).run()
    if two_files:
        app.radio[0].set_value("Two files").run()
        app.text_input[0].set_value("orders")
        app.text_input[1].set_value("products")
        app.file_uploader[1].set_value(
            ("products.csv", b"pid,name\np1,A\np2,B\n", "text/csv")
        )
    app.file_uploader[0].set_value(
        ("orders.csv", b"pid,amount\np1,100\np2,2000\n", "text/csv")
    )
    app.text_area[0].set_value(
        "Merge orders and products on pid."
        if two_files else "Keep rows where amount > 1000."
    )
    app.run()
    assert not app.exception
    generate.assert_not_called()

    next(button for button in app.button if button.label == "Generate").click().run()

    assert not app.exception
    generate.assert_called_once()
    assert app.session_state["error_message"] is None
    output = pd.read_csv(BytesIO(app.session_state["output_bytes"]))
    pd.testing.assert_frame_equal(output, pd.DataFrame(expected))
    assert len(app.get("download_button")) == 1
    events = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(events) == 1
    assert events[0]["success"] is True
