import pandas as pd
import pytest

from snapscript.core import execution_backend
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


def test_unsafe_merge_code_never_reaches_a_backend(tmp_path, monkeypatch):
    def unexpected_execute(*args, **kwargs):
        pytest.fail("Unsafe code must not reach any execution backend")

    monkeypatch.setattr(execution_backend, "execute", unexpected_execute)
    result, calls = run_mocked_merge(write_inputs(tmp_path), tmp_path / "merged.csv", "Merge files.", "import os\nos.system('id')", monkeypatch)

    assert not result.success
    assert "Safety violation" in result.stderr
    assert len(calls) == 1
