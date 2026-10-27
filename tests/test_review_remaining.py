"""Behavior regressions for remaining CSV and language review findings."""
from concurrent.futures import ThreadPoolExecutor
import csv
from io import BytesIO

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from snapscript.config import AppConfig
from snapscript.core import code_generator, sandbox_executor, schema_inspector, task_advisor
from snapscript.core.models import ColumnInfo, SchemaReport
from snapscript.interfaces import web
from snapscript.interfaces.web_inputs import load_output_preview


def test_large_multiline_csv_fields_are_counted_without_global_changes(tmp_path):
    value = "x" * 140000 + '\nquoted, "value"'
    files = []
    for index in range(2):
        path = tmp_path / f"input_{index}.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["notes", "id"])
            writer.writerows([(value, 1), ("short", 2), ("final", 3)])
        files.append(path)
    original_limit = csv.field_size_limit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(schema_inspector.inspect, files))
    assert [report.row_count for report in reports] == [3, 3]
    assert all(len(report.sample_rows[0]["notes"]) == len(value) for report in reports)
    assert csv.field_size_limit() == original_limit


@pytest.mark.parametrize("encoding,text", [
    ("utf-8", "café"), ("cp1252", "café"),
    ("big5", "台北測試資料"), ("utf-16", "台北測試資料"),
])
def test_encoded_outputs_validate_preview_and_preserve_bytes(tmp_path, encoding, text):
    source, output = tmp_path / "input.csv", tmp_path / "out.csv"
    source.write_text("value\n1\n")
    code = (
        "from _snapscript_paths import OUTPUT_PATH\nimport pandas as pd\n"
        f"pd.DataFrame({{'name': [{text!r}] * 10}}).to_csv(OUTPUT_PATH, index=False, encoding={encoding!r})\n"
    )
    result = sandbox_executor.execute(code, source, output, config=AppConfig())
    assert result.success, result.stderr
    expected = pd.DataFrame({"name": [text] * 10})
    actual_bytes = output.read_bytes()
    pd.testing.assert_frame_equal(load_output_preview(actual_bytes, ".csv"), expected)
    buffer = BytesIO()
    expected.to_csv(buffer, index=False, encoding=encoding)
    assert actual_bytes == buffer.getvalue()


def test_chinese_advice_is_unassessed_without_false_missing_details():
    schema = SchemaReport("input.csv", "csv", 1, 10, columns=[ColumnInfo("amount", "int64")])
    for task in ("保留 amount 大於 1000 的資料", "整理資料"):
        advice = task_advisor.advise_task(task, schema)
        assert advice.quality == "not_assessed"
        assert advice.missing_details == []
        assert advice.suggested_task is None


def test_real_app_chinese_advice_does_not_block_generate(monkeypatch):
    monkeypatch.setattr(web, "AppConfig", lambda: AppConfig(sandbox_backend="subprocess"))
    monkeypatch.setattr(code_generator, "generate", lambda *a, **k: pytest.fail("No generation was requested"))
    app = AppTest.from_file("app.py", default_timeout=10).run()
    app.file_uploader[0].set_value(("orders.csv", b"amount\n1\n2000\n", "text/csv"))
    app.text_area[0].set_value("保留 amount 大於 1000 的資料").run()
    assert not app.exception
    assert any(info.value == "Status: Not Assessed" for info in app.info)
    assert not next(button for button in app.button if button.label == "Generate").disabled
