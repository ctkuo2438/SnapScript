from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from snapscript.core.models import (
    ExecutionResult,
    GeneratedScript,
    PromptPayload,
    SafetyResult,
)
from snapscript.interfaces import cli


FIXTURE_DIR = Path("tests/fixtures/integration")
MANIFEST_PATH = FIXTURE_DIR / "FIXTURE_MANIFEST.json"
REAL_PROVIDER_ENV = "SNAPSCRIPT_REAL_PROVIDER"


def _load_manifest() -> dict[str, dict[str, object]]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


MANIFEST = _load_manifest()


GATE_TASKS = {
    "task_01": {
        "input": "task_01_customers.csv",
        "prompt": (
            "Remove duplicate rows by email, keeping the row with the latest "
            "created_at date."
        ),
        "code": """
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd

df = pd.read_csv(INPUT_PATH)
df["created_at"] = pd.to_datetime(df["created_at"])
out = df.sort_values("created_at").drop_duplicates("email", keep="last")
out["created_at"] = out["created_at"].dt.strftime("%Y-%m-%d")
out.to_csv(OUTPUT_PATH, index=False)
""",
        "assert": "_assert_task_01",
    },
    "task_02": {
        "input": "task_02_orders.csv",
        "prompt": "Keep only orders where amount is greater than 1000.",
        "code": """
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd

df = pd.read_csv(INPUT_PATH)
out = df[df["amount"] > 1000]
out.to_csv(OUTPUT_PATH, index=False)
""",
        "assert": "_assert_task_02",
    },
    "task_03": {
        "input": "task_03_contacts.csv",
        "prompt": "Create a full_name column by combining first_name and last_name.",
        "code": """
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd

df = pd.read_csv(INPUT_PATH)
df["full_name"] = df["first_name"] + " " + df["last_name"]
df.to_csv(OUTPUT_PATH, index=False)
""",
        "assert": "_assert_task_03",
    },
    "task_04": {
        "input": "task_04_logs.csv",
        "prompt": "Convert event_date from MM/DD/YYYY to YYYY-MM-DD.",
        "code": """
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd

df = pd.read_csv(INPUT_PATH)
df["event_date"] = pd.to_datetime(
    df["event_date"], format="%m/%d/%Y"
).dt.strftime("%Y-%m-%d")
df.to_csv(OUTPUT_PATH, index=False)
""",
        "assert": "_assert_task_04",
    },
    "task_05": {
        "input": "task_05_mixed.csv",
        "prompt": "Convert price to numeric and drop rows with invalid prices.",
        "code": """
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd

df = pd.read_csv(INPUT_PATH)
df["price"] = pd.to_numeric(df["price"], errors="coerce")
out = df.dropna(subset=["price"])
out.to_csv(OUTPUT_PATH, index=False)
""",
        "assert": "_assert_task_05",
    },
    "task_06": {
        "input": "task_06_sparse.csv",
        "prompt": "Fill missing notes with 'No notes'.",
        "code": """
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd

df = pd.read_csv(INPUT_PATH)
df["notes"] = df["notes"].fillna("No notes")
df.to_csv(OUTPUT_PATH, index=False)
""",
        "assert": "_assert_task_06",
    },
    "task_07": {
        "input": "task_07_status.csv",
        "prompt": "Replace status value old with archived.",
        "code": """
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd

df = pd.read_csv(INPUT_PATH)
df.loc[df["status"] == "old", "status"] = "archived"
df.to_csv(OUTPUT_PATH, index=False)
""",
        "assert": "_assert_task_07",
    },
    "task_08": {
        "input": "task_08_scores.csv",
        "prompt": "Sort by score descending and keep the top 10 rows.",
        "code": """
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd

df = pd.read_csv(INPUT_PATH)
out = df.sort_values("score", ascending=False).head(10)
out.to_csv(OUTPUT_PATH, index=False)
""",
        "assert": "_assert_task_08",
    },
    "task_09": {
        "input": "task_09_events.csv",
        "prompt": "Count rows per event_type.",
        "code": """
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd

df = pd.read_csv(INPUT_PATH)
out = df.groupby("event_type").size().reset_index(name="count")
out.to_csv(OUTPUT_PATH, index=False)
""",
        "assert": "_assert_task_09",
    },
    "task_10": {
        "input": "task_10_big.csv",
        "prompt": "Filter rows where region equals West.",
        "code": """
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd

df = pd.read_csv(INPUT_PATH)
out = df[df["region"] == "West"]
out.to_csv(OUTPUT_PATH, index=False)
""",
        "assert": "_assert_task_10",
    },
}


AssertionFn = Callable[[pd.DataFrame, Path, dict[str, object], float], None]


ASSERTIONS: dict[str, AssertionFn] = {}


def _register(name: str) -> Callable[[AssertionFn], AssertionFn]:
    def decorator(func: AssertionFn) -> AssertionFn:
        ASSERTIONS[name] = func
        return func

    return decorator


@_register("_assert_task_01")
def _assert_task_01(
    output: pd.DataFrame, input_path: Path, metadata: dict[str, object], elapsed: float
) -> None:
    duplicate_email = str(metadata["known_duplicate_email"])
    source = pd.read_csv(input_path)
    latest_created_at = source.loc[
        source["email"] == duplicate_email, "created_at"
    ].max()
    alice_rows = output[output["email"] == duplicate_email]

    assert len(output) == metadata["output_rows"]
    assert output["email"].nunique() == metadata["unique_emails"]
    assert len(alice_rows) == 1
    assert alice_rows.iloc[0]["created_at"] == latest_created_at


@_register("_assert_task_02")
def _assert_task_02(
    output: pd.DataFrame, input_path: Path, metadata: dict[str, object], elapsed: float
) -> None:
    assert len(output) == metadata["output_rows"]
    assert (output["amount"] > 1000).all()


@_register("_assert_task_03")
def _assert_task_03(
    output: pd.DataFrame, input_path: Path, metadata: dict[str, object], elapsed: float
) -> None:
    assert len(output) == metadata["output_rows"]
    assert "full_name" in output.columns
    assert output.iloc[0]["full_name"] == metadata["first_row_full_name"]


@_register("_assert_task_04")
def _assert_task_04(
    output: pd.DataFrame, input_path: Path, metadata: dict[str, object], elapsed: float
) -> None:
    assert len(output) == metadata["output_rows"]
    assert output.iloc[0]["event_date"] == metadata["known_output_date"]


@_register("_assert_task_05")
def _assert_task_05(
    output: pd.DataFrame, input_path: Path, metadata: dict[str, object], elapsed: float
) -> None:
    assert len(output) == metadata["output_rows"]
    assert pd.api.types.is_numeric_dtype(output["price"])


@_register("_assert_task_06")
def _assert_task_06(
    output: pd.DataFrame, input_path: Path, metadata: dict[str, object], elapsed: float
) -> None:
    assert len(output) == metadata["output_rows"]
    assert output["notes"].isna().sum() == metadata["null_count_output"]
    assert (output["notes"] == "No notes").sum() == metadata["filled_count"]


@_register("_assert_task_07")
def _assert_task_07(
    output: pd.DataFrame, input_path: Path, metadata: dict[str, object], elapsed: float
) -> None:
    assert len(output) == metadata["output_rows"]
    assert (output["status"] == "old").sum() == 0
    assert (output["status"] == "archived").sum() == metadata["known_old_count"]


@_register("_assert_task_08")
def _assert_task_08(
    output: pd.DataFrame, input_path: Path, metadata: dict[str, object], elapsed: float
) -> None:
    assert len(output) == metadata["output_rows"]
    assert output["score"].is_monotonic_decreasing
    assert output.iloc[0]["score"] == metadata["max_score"]


@_register("_assert_task_09")
def _assert_task_09(
    output: pd.DataFrame, input_path: Path, metadata: dict[str, object], elapsed: float
) -> None:
    count_column = _find_count_column(output)

    assert len(output) == metadata["output_rows"]
    assert output[count_column].sum() == metadata["total_sum"]
    assert output.set_index("event_type")[count_column].to_dict() == metadata[
        "event_counts"
    ]


@_register("_assert_task_10")
def _assert_task_10(
    output: pd.DataFrame, input_path: Path, metadata: dict[str, object], elapsed: float
) -> None:
    assert len(output) == metadata["output_rows"]
    assert (output["region"] == "West").all()
    assert elapsed < 25


@pytest.mark.parametrize("task_id", sorted(GATE_TASKS))
def test_cli_gate_task(
    task_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert set(GATE_TASKS) == set(MANIFEST)

    task = GATE_TASKS[task_id]
    input_path = FIXTURE_DIR / str(task["input"])
    output_path = tmp_path / f"{task_id}_output.csv"
    real_provider = os.environ.get(REAL_PROVIDER_ENV) == "1"
    generate_calls: list[PromptPayload] = []
    safety_calls: list[str] = []
    sandbox_calls: list[tuple[str, Path, Path]] = []

    if not real_provider:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(
            cli.code_generator,
            "generate",
            _mock_generate(str(task["code"]), generate_calls),
        )

    original_check = cli.safety_checker.check
    original_execute = cli.sandbox_executor.execute

    def check_spy(code: str) -> SafetyResult:
        safety_calls.append(code)
        return original_check(code)

    def execute_spy(
        code: str, input_path_arg: Path, output_path_arg: Path
    ) -> ExecutionResult:
        sandbox_calls.append((code, input_path_arg, output_path_arg))
        return original_execute(code, input_path_arg, output_path_arg)

    monkeypatch.setattr(cli.safety_checker, "check", check_spy)
    monkeypatch.setattr(cli.sandbox_executor, "execute", execute_spy)

    start = time.monotonic()
    status = cli.main(
        [
            str(task["prompt"]),
            "--file",
            str(input_path),
            "--output",
            str(output_path),
            "--yes",
        ]
    )
    elapsed = time.monotonic() - start

    assert status == 0
    assert output_path.exists()
    assert safety_calls
    assert sandbox_calls
    assert sandbox_calls[-1][1] == input_path
    assert sandbox_calls[-1][2] == output_path

    if not real_provider:
        assert len(generate_calls) == 1
        assert safety_calls == [str(task["code"])]
        assert len(sandbox_calls) == 1

    output = pd.read_csv(output_path)
    ASSERTIONS[str(task["assert"])](output, input_path, MANIFEST[task_id], elapsed)


def _mock_generate(
    code: str, calls: list[PromptPayload]
) -> Callable[[PromptPayload, str | None], GeneratedScript]:
    def fake_generate(
        prompt: PromptPayload, model: str | None = None
    ) -> GeneratedScript:
        assert model is None
        calls.append(prompt)
        return GeneratedScript(
            code=code,
            raw_response=code,
            model="mock-gate-model",
            input_tokens=0,
            output_tokens=0,
        )

    return fake_generate


def _find_count_column(output: pd.DataFrame) -> str:
    numeric_columns = [
        column
        for column in output.columns
        if column != "event_type" and pd.api.types.is_numeric_dtype(output[column])
    ]
    assert numeric_columns
    return numeric_columns[0]
