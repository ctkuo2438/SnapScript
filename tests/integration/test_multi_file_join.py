from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from snapscript.core import code_generator, prompt_builder, retry_handler, schema_inspector
from snapscript.core.models import ExecutionResult, GeneratedScript, InputFileSpec


ORDERS_CSV = """order_id,pid,amount
1,p1,100
2,p2,200
3,p3,300
"""

PRODUCTS_CSV = """pid,product_name
p1,Keyboard
p2,Mouse
"""


INNER_JOIN_CODE = """
from _snapscript_paths import INPUT_PATHS, OUTPUT_PATH
import pandas as pd

orders = pd.read_csv(INPUT_PATHS["orders"])
products = pd.read_csv(INPUT_PATHS["products"])
joined = orders.merge(products, on="pid", how="inner")
joined.to_csv(OUTPUT_PATH, index=False)
"""


LEFT_JOIN_CODE = """
from _snapscript_paths import INPUT_PATHS, OUTPUT_PATH
import pandas as pd

orders = pd.read_csv(INPUT_PATHS["orders"])
products = pd.read_csv(INPUT_PATHS["products"])
joined = orders.merge(products, on="pid", how="left")
joined.to_csv(OUTPUT_PATH, index=False)
"""


def _write_join_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    orders_path = tmp_path / "orders.csv"
    products_path = tmp_path / "products.csv"
    orders_path.write_text(ORDERS_CSV, encoding="utf-8")
    products_path.write_text(PRODUCTS_CSV, encoding="utf-8")
    return orders_path, products_path


def _assert_generated_code_uses_multi_file_paths(
    generated_code: str,
    orders_path: Path,
    products_path: Path,
) -> None:
    assert "INPUT_PATHS" in generated_code
    assert "OUTPUT_PATH" in generated_code
    assert 'INPUT_PATHS["orders"]' in generated_code
    assert 'INPUT_PATHS["products"]' in generated_code
    assert re.search(r"(?<![A-Za-z0-9_])INPUT_PATH(?![A-Za-z0-9_])", generated_code) is None
    assert str(orders_path) not in generated_code
    assert str(products_path) not in generated_code
    assert str(orders_path.parent) not in generated_code


def _run_join_pipeline(
    task_text: str,
    generated_code: str,
    tmp_path: Path,
    monkeypatch,
) -> tuple[ExecutionResult, pd.DataFrame]:
    orders_path, products_path = _write_join_fixtures(tmp_path)
    _assert_generated_code_uses_multi_file_paths(
        generated_code,
        orders_path,
        products_path,
    )
    monkeypatch.delenv("SNAPSCRIPT_SANDBOX_BACKEND", raising=False)

    def fake_generate(_prompt, model: str | None = None) -> GeneratedScript:
        return GeneratedScript(
            code=generated_code,
            raw_response=generated_code,
            model=model or "mock-provider",
        )

    monkeypatch.setattr(code_generator, "generate", fake_generate)

    input_specs = [
        InputFileSpec(name="orders", path=orders_path),
        InputFileSpec(name="products", path=products_path),
    ]
    multi_schema = schema_inspector.inspect_many(input_specs)
    prompt = prompt_builder.build_many(task_text, multi_schema)
    output_path = tmp_path / "joined.csv"

    result = retry_handler.run_many(prompt, input_specs, output_path)

    assert result.success is True, result.stderr
    assert output_path.exists()
    output = pd.read_csv(output_path)
    return result, output


def test_mocked_provider_inner_join_uses_input_paths_and_real_sandbox(
    tmp_path: Path,
    monkeypatch,
) -> None:
    result, output = _run_join_pipeline(
        'Please merge orders and products using the "pid" column with an inner join.',
        INNER_JOIN_CODE,
        tmp_path,
        monkeypatch,
    )

    assert result.success is True
    assert len(output) == 2
    assert {"order_id", "pid", "amount", "product_name"}.issubset(output.columns)
    assert set(output["pid"]) == {"p1", "p2"}
    assert "p3" not in set(output["pid"])


def test_mocked_provider_left_join_uses_input_paths_and_real_sandbox(
    tmp_path: Path,
    monkeypatch,
) -> None:
    result, output = _run_join_pipeline(
        (
            'Please merge orders and products using the "pid" column with a left '
            "join and keep all orders."
        ),
        LEFT_JOIN_CODE,
        tmp_path,
        monkeypatch,
    )

    assert result.success is True
    assert len(output) == 3
    assert {"order_id", "pid", "amount", "product_name"}.issubset(output.columns)
    assert set(output["pid"]) == {"p1", "p2", "p3"}
    p3_product_name = output.loc[output["pid"] == "p3", "product_name"].iloc[0]
    assert pd.isna(p3_product_name) or p3_product_name == ""
