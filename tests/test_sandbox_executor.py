from pathlib import Path

import pandas as pd
import pytest

from snapscript.config import AppConfig
from snapscript.core import sandbox_executor
from snapscript.core.models import ExecutionResult


def _write_input_csv(path: Path) -> None:
    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [500, 1500, 2500],
        }
    ).to_csv(path, index=False)


def test_execute_runs_code_in_temp_workspace_and_copies_valid_csv_output(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "orders.csv"
    output_path = tmp_path / "filtered.csv"
    _write_input_csv(input_path)
    code = """
from pathlib import Path
import pandas as pd
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH

expected = "INPUT" + "_PATH"
assert expected in Path("script.py").read_text()
input_path = Path(INPUT_PATH)
output_path = Path(OUTPUT_PATH)
assert input_path.parent.resolve() == Path.cwd().resolve()
assert output_path.parent.resolve() == Path.cwd().resolve()
df = pd.read_csv(INPUT_PATH)
df = df[df["amount"] > 1000]
df.to_csv(OUTPUT_PATH, index=False)
print("filtered rows")
"""

    result = sandbox_executor.execute(code, input_path, output_path)

    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert result.exit_code == 0
    assert "filtered rows" in result.stdout
    assert result.stderr == ""
    assert result.output_files == [output_path]
    assert output_path.exists()
    assert input_path.exists()

    output = pd.read_csv(output_path)
    assert output["order_id"].tolist() == [2, 3]


def test_execute_returns_failure_when_output_is_missing(tmp_path: Path) -> None:
    input_path = tmp_path / "orders.csv"
    output_path = tmp_path / "missing.csv"
    _write_input_csv(input_path)

    result = sandbox_executor.execute("print('no output')\n", input_path, output_path)

    assert result.success is False
    assert result.exit_code == 0
    assert "Output file was not created" in result.stderr
    assert not output_path.exists()
    assert input_path.exists()


def test_execute_returns_failure_when_output_is_empty(tmp_path: Path) -> None:
    input_path = tmp_path / "orders.csv"
    output_path = tmp_path / "empty.csv"
    _write_input_csv(input_path)
    code = """
from pathlib import Path
from _snapscript_paths import OUTPUT_PATH

Path(OUTPUT_PATH).write_text("")
"""

    result = sandbox_executor.execute(code, input_path, output_path)

    assert result.success is False
    assert "Output unreadable" in result.stderr or "Output is empty" in result.stderr
    assert not output_path.exists()
    assert input_path.exists()


def test_execute_returns_failure_when_output_is_unreadable(tmp_path: Path) -> None:
    input_path = tmp_path / "orders.csv"
    output_path = tmp_path / "broken.xlsx"
    _write_input_csv(input_path)
    code = """
from pathlib import Path
from _snapscript_paths import OUTPUT_PATH

Path(OUTPUT_PATH).write_text("not a workbook")
"""

    result = sandbox_executor.execute(code, input_path, output_path)

    assert result.success is False
    assert "Output unreadable" in result.stderr
    assert not output_path.exists()
    assert input_path.exists()


def test_execute_returns_failure_on_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "orders.csv"
    output_path = tmp_path / "timeout.csv"
    _write_input_csv(input_path)
    monkeypatch.setattr(
        sandbox_executor,
        "AppConfig",
        lambda: AppConfig(execution_timeout_seconds=1),
    )

    result = sandbox_executor.execute("while True:\n    pass\n", input_path, output_path)

    assert result.success is False
    assert result.exit_code == -1
    assert "timed out" in result.stderr.lower()
    assert not output_path.exists()
    assert input_path.exists()


def test_execute_returns_failure_on_nonzero_exit(tmp_path: Path) -> None:
    input_path = tmp_path / "orders.csv"
    output_path = tmp_path / "failed.csv"
    _write_input_csv(input_path)

    result = sandbox_executor.execute(
        "raise RuntimeError('transformation failed')\n",
        input_path,
        output_path,
    )

    assert result.success is False
    assert result.exit_code != 0
    assert "RuntimeError" in result.stderr
    assert not output_path.exists()
    assert input_path.exists()


def test_execute_copies_validated_output_before_cleanup(tmp_path: Path) -> None:
    input_path = tmp_path / "orders.csv"
    output_path = tmp_path / "nested" / "result.csv"
    _write_input_csv(input_path)
    code = """
import pandas as pd
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH

df = pd.read_csv(INPUT_PATH)
df.to_csv(OUTPUT_PATH, index=False)
"""

    result = sandbox_executor.execute(code, input_path, output_path)

    assert result.success is True
    assert output_path.exists()
    assert pd.read_csv(output_path).shape == (3, 2)
    assert input_path.exists()


def test_sandbox_executor_core_has_no_ui_dependencies() -> None:
    source = Path("src/snapscript/core/sandbox_executor.py").read_text()

    assert "argparse" not in source
    assert "rich" not in source
    assert "streamlit" not in source
    assert "sys.argv" not in source
    assert ".replace(" not in source
