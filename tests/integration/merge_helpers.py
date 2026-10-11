"""Small shared fixtures for deterministic and opt-in merge acceptance tests."""

from pathlib import Path

import pandas as pd

from snapscript.config import AppConfig
from snapscript.core import code_generator, prompt_builder, retry_handler, schema_inspector
from snapscript.core.models import ExecutionResult, GeneratedScript, InputFileSpec


ORDERS_CSV = "order_id,pid,amount\n1,p1,100\n2,p2,200\n3,p3,300\n"
PRODUCTS_CSV = "pid,product_name\np1,Keyboard\np2,Mouse\n"
MERGE_TEMPLATE = '''
from _snapscript_paths import INPUT_PATHS, OUTPUT_PATH
import pandas as pd

orders = pd.read_csv(INPUT_PATHS["orders"])
products = pd.read_csv(INPUT_PATHS["products"])
key = {key}
if key is None:
    common = sorted(set(orders.columns) & set(products.columns))
    if len(common) != 1:
        raise ValueError("Input validation: specify a merge key; common columns: " + ", ".join(common))
    key = common[0]
for name, frame in [("orders", orders), ("products", products)]:
    if key not in frame.columns:
        raise ValueError("Input validation: " + name + " missing column " + key + "; available columns: " + ", ".join(frame.columns))
    if frame[key].isna().any():
        raise ValueError("Input validation: " + name + " has null key " + key)
if orders[key].dtype != products[key].dtype:
    raise ValueError("Input validation: orders/products key " + key + " dtypes differ; align the types")
joined = orders.merge(products, on=key, how={join})
joined.to_csv(OUTPUT_PATH, index=False)
'''


def merge_code(key: str | None = "pid", join: str = "inner") -> str:
    return MERGE_TEMPLATE.format(key=repr(key), join=repr(join))


def write_inputs(
    directory: Path, orders: str = ORDERS_CSV, products: str = PRODUCTS_CSV,
) -> list[InputFileSpec]:
    specs = []
    for name, contents in (("orders", orders), ("products", products)):
        path = directory / f"{name}.csv"
        path.write_text(contents, encoding="utf-8")
        specs.append(InputFileSpec(name=name, path=path))
    return specs


def expected_merge(join: str = "inner") -> pd.DataFrame:
    rows = [(1, "p1", 100, "Keyboard"), (2, "p2", 200, "Mouse")]
    if join == "left":
        rows.append((3, "p3", 300, float("nan")))
    return pd.DataFrame(rows, columns=["order_id", "pid", "amount", "product_name"])


def run_mocked_merge(
    inputs: list[InputFileSpec], output: Path, task: str, code: str,
    monkeypatch, config: AppConfig | None = None,
) -> tuple[ExecutionResult, list]:
    calls = []
    original = [spec.path.read_bytes() for spec in inputs]

    def fake_generate(prompt, model=None, config=None):
        calls.append(prompt)
        return GeneratedScript(code=code, raw_response=code, model=model or "mock-provider")

    monkeypatch.setattr(code_generator, "generate", fake_generate)
    schema = schema_inspector.inspect_many(inputs)
    prompt = prompt_builder.build_many(task, schema)
    result = retry_handler.run_many(
        prompt, inputs, output, config=config or AppConfig(sandbox_backend="subprocess"),
    )
    assert [spec.path.read_bytes() for spec in inputs] == original
    return result, calls
