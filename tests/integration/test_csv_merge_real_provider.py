"""Explicit, independent Claude acceptance gate; never part of ordinary pytest."""

import os

import pandas as pd
import pytest
from dotenv import load_dotenv

from snapscript.config import AppConfig
from snapscript.core import prompt_builder, retry_handler, schema_inspector
from merge_helpers import expected_merge, write_inputs


pytestmark = pytest.mark.skipif(os.getenv("SNAPSCRIPT_REAL_PROVIDER") != "1", reason="Real provider is explicit opt-in")


@pytest.fixture
def provider_config():
    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("Real provider requires a configured API key")
    return AppConfig(sandbox_backend="subprocess", max_retries=0)


@pytest.mark.parametrize("task,join", [
    ("Merge orders and products.", "inner"),
    ("Merge orders and products on pid with a left join; keep every order.", "left"),
])
def test_claude_merge_matches_spec(tmp_path, provider_config, task, join):
    inputs = write_inputs(tmp_path)
    before = [spec.path.read_bytes() for spec in inputs]
    prompt = prompt_builder.build_many(task, schema_inspector.inspect_many(inputs))
    output = tmp_path / "merged.csv"

    result = retry_handler.run_many(prompt, inputs, output, config=provider_config)

    assert result.success, result.stderr
    pd.testing.assert_frame_equal(pd.read_csv(output), expected_merge(join))
    assert [spec.path.read_bytes() for spec in inputs] == before


@pytest.mark.parametrize("products,task,details", [
    ("sku,product_name\np1,Keyboard\n", "Merge orders and products on pid.", ("products", "pid", "sku", "product_name")),
    ("pid,order_id,product_name\np1,1,Keyboard\n", "Merge orders and products.", ("key", "pid", "order_id")),
])
def test_claude_reports_key_errors(tmp_path, provider_config, products, task, details):
    inputs = write_inputs(tmp_path, products=products)
    before = [spec.path.read_bytes() for spec in inputs]
    prompt = prompt_builder.build_many(task, schema_inspector.inspect_many(inputs))
    output = tmp_path / "merged.csv"

    result = retry_handler.run_many(prompt, inputs, output, config=provider_config)

    assert not result.success
    assert "Input validation:" in result.stderr
    for detail in details:
        assert detail in result.stderr.lower()
    assert not output.exists()
    assert [spec.path.read_bytes() for spec in inputs] == before
