from unittest.mock import Mock

import pandas as pd
import pytest

from snapscript.config import AppConfig
from snapscript.core import code_generator, execution_backend, retry_handler
from snapscript.core.models import GeneratedScript, PromptPayload
from merge_helpers import expected_merge, merge_code, run_mocked_merge, write_inputs


@pytest.mark.parametrize("key,join", [(None, "inner"), ("pid", "inner"), ("pid", "left")])
def test_merge_matches_complete_expected_result(tmp_path, monkeypatch, key, join):
    inputs = write_inputs(tmp_path)
    output = tmp_path / "merged.csv"
    result, calls = run_mocked_merge(inputs, output, "Merge orders and products.", merge_code(key, join), monkeypatch)

    assert result.success, result.stderr
    assert len(calls) == 1
    pd.testing.assert_frame_equal(pd.read_csv(output), expected_merge(join))


@pytest.mark.parametrize("orders,products,key,error", [
    ("order_id,pid,amount\n1,p1,100\n", "sku,product_name\np1,Keyboard\n", "pid", "products missing column pid; available columns: sku, product_name"),
    ("order_id,pid,amount\n1,p1,100\n", "pid,order_id,product_name\np1,1,Keyboard\n", None, "specify a merge key; common columns: order_id, pid"),
    ("order_id,pid,amount\n1,p1,100\n", "sku,product_name\np1,Keyboard\n", None, "specify a merge key"),
    ("order_id,pid,amount\n1,,100\n2,p2,200\n", "pid,product_name\np1,Keyboard\n", "pid", "orders has null key pid"),
    ("order_id,pid,amount\n1,1,100\n", "pid,product_name\np1,Keyboard\n", "pid", "orders/products key pid dtypes differ"),
])
def test_merge_input_errors_are_actionable_and_not_retried(tmp_path, monkeypatch, orders, products, key, error):
    inputs = write_inputs(tmp_path, orders, products)
    output = tmp_path / "merged.csv"
    result, calls = run_mocked_merge(inputs, output, "Merge files.", merge_code(key), monkeypatch)

    assert not result.success
    assert "Input validation:" in result.stderr
    assert error in result.stderr
    assert len(calls) == 1
    assert not output.exists()


def test_duplicate_keys_keep_all_pairings(tmp_path, monkeypatch):
    inputs = write_inputs(
        tmp_path, "order_id,pid,amount\n1,p1,100\n4,p1,400\n",
        "pid,product_name\np1,Keyboard\np1,KeyboardAlt\n",
    )
    output = tmp_path / "merged.csv"
    result, _ = run_mocked_merge(inputs, output, "Merge on pid.", merge_code(), monkeypatch)

    assert result.success, result.stderr
    expected = pd.DataFrame([
        (1, "p1", 100, "Keyboard"), (1, "p1", 100, "KeyboardAlt"),
        (4, "p1", 400, "Keyboard"), (4, "p1", 400, "KeyboardAlt"),
    ], columns=["order_id", "pid", "amount", "product_name"])
    pd.testing.assert_frame_equal(pd.read_csv(output), expected)


def test_no_matching_rows_returns_empty_output_error(tmp_path, monkeypatch):
    inputs = write_inputs(tmp_path, products="pid,product_name\np9,Other\n")
    output = tmp_path / "merged.csv"
    result, calls = run_mocked_merge(inputs, output, "Merge on pid.", merge_code(), monkeypatch)

    assert not result.success
    assert result.stderr == "Output is empty"
    assert len(calls) == 1
    assert not output.exists()


@pytest.mark.parametrize("backend", ["subprocess", "docker"])
@pytest.mark.parametrize("many", [False, True])
@pytest.mark.parametrize("code", [
    pytest.param("import os\nos.system('id')", id="blocked-import"),
    pytest.param("callback = eval", id="builtin-alias"),
    pytest.param("().__class__.__base__.__subclasses__()", id="dunder-chain"),
    pytest.param("import pandas as pd\npd.io.common.os.system('true')", id="pandas-module"),
    pytest.param("import pandas as pd\npd.read_csv('/etc/passwd')", id="pandas-path"),
    pytest.param("from pathlib import Path\nPath('/etc/passwd').open()", id="path-open"),
])
def test_unsafe_merge_code_never_reaches_a_backend(tmp_path, monkeypatch, backend, many, code):
    def unexpected_execute(*args, **kwargs):
        pytest.fail("Unsafe code must not reach any execution backend")

    inputs = write_inputs(tmp_path)
    originals = [spec.path.read_bytes() for spec in inputs]
    output = tmp_path / "merged.csv"
    generator = Mock(return_value=GeneratedScript(code, code, "fixture"))
    monkeypatch.setattr(code_generator, "generate", generator)
    monkeypatch.setattr(execution_backend, "execute", unexpected_execute)
    monkeypatch.setattr(execution_backend, "preflight", lambda config: None)
    run = retry_handler.run_many if many else retry_handler.run
    result = run(
        PromptPayload("system", "Process input rows."),
        inputs if many else inputs[0].path, output,
        config=AppConfig(sandbox_backend=backend),
    )

    assert not result.success
    assert result.error_category == "safety_violation"
    assert "Safety violation" in result.stderr
    assert generator.call_count == 1
    assert not output.exists()
    assert [spec.path.read_bytes() for spec in inputs] == originals
