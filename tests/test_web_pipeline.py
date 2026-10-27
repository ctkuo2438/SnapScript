"""Uploaded data produces complete results and temporary inputs are removed."""
from dataclasses import asdict
from io import BytesIO
from unittest.mock import Mock

import pandas as pd
import pytest

from helpers.web_helpers import COPY_CODE, INPUT_BYTES, METRICS, TASK
from snapscript.config import AppConfig
from snapscript.core.models import GeneratedScript
from snapscript.interfaces import web_pipeline


@pytest.mark.parametrize("two_files", [False, True])
@pytest.mark.parametrize("with_metadata", [False, True])
def test_uploaded_pipeline_preserves_data_metadata_and_temp_lifecycle(monkeypatch, two_files, with_metadata):
    code = COPY_CODE if not two_files else (
        "from _snapscript_paths import INPUT_PATHS, OUTPUT_PATH\nimport pandas as pd\n"
        "pd.read_csv(INPUT_PATHS['orders']).to_csv(OUTPUT_PATH, index=False)\n"
    )
    generate = Mock(return_value=GeneratedScript(code, code, METRICS.model, api_call=METRICS))
    from snapscript.core import code_generator
    monkeypatch.setattr(code_generator, "generate", generate)
    name = "run_many" if two_files else "run"
    run = Mock(wraps=getattr(web_pipeline.retry_handler, name))
    monkeypatch.setattr(web_pipeline.retry_handler, name, run)
    audit = {} if with_metadata else None
    config = AppConfig(sandbox_backend="subprocess", max_retries=0)
    if two_files:
        result, output, filename = web_pipeline.run_uploaded_tasks_many(
            first_file_bytes=INPUT_BYTES, first_suffix=".csv", first_logical_name="orders",
            first_uploaded_file_name="orders.csv", second_file_bytes=INPUT_BYTES,
            second_suffix=".csv", second_logical_name="products", second_uploaded_file_name="products.csv",
            task_text=TASK, audit_metadata=audit, config=config,
        )
    else:
        result, output, filename = web_pipeline.run_uploaded_task(
            INPUT_BYTES, ".csv", TASK, uploaded_file_name="orders.csv", audit_metadata=audit, config=config,
        )
    assert result.success, result.stderr
    pd.testing.assert_frame_equal(pd.read_csv(BytesIO(output)), pd.read_csv(BytesIO(INPUT_BYTES)))
    assert filename == ("snapscript_output.csv" if two_files else "orders_snapscript_output.csv")
    if audit is not None:
        assert audit["provider_called"] is True
        assert audit["api_calls"] == [asdict(METRICS)]
        assert "sample_rows" not in str(audit["schema_summary"])
    prompt_text = generate.call_args.args[0].user_prompt
    assert TASK in prompt_text
    input_arg, output_path = run.call_args.args[1:3]
    paths = [item.path for item in input_arg] if two_files else [input_arg]
    assert all(path.parent == output_path.parent for path in paths)
    assert all(str(path) not in prompt_text for path in paths)
    assert not output_path.parent.exists()
