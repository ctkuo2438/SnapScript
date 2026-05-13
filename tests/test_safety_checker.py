from pathlib import Path
from runpy import run_path

import pytest

from snapscript.core import safety_checker
from snapscript.core.models import SafetyResult


_MALICIOUS_FIXTURES = run_path("tests/fixtures/unit/malicious_code.py")
UNSAFE_CALL_SNIPPETS = _MALICIOUS_FIXTURES["UNSAFE_CALL_SNIPPETS"]
UNSAFE_IMPORT_SNIPPETS = _MALICIOUS_FIXTURES["UNSAFE_IMPORT_SNIPPETS"]
UNSAFE_OPEN_SNIPPETS = _MALICIOUS_FIXTURES["UNSAFE_OPEN_SNIPPETS"]


SAFE_PANDAS_CODE = """
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd

df = pd.read_csv(INPUT_PATH)
df = df[df["amount"] > 1000]
df.to_csv(OUTPUT_PATH, index=False)
"""


def test_check_allows_normal_pandas_input_output_code() -> None:
    result = safety_checker.check(SAFE_PANDAS_CODE)

    assert isinstance(result, SafetyResult)
    assert result.is_safe is True
    assert result.ast_valid is True
    assert result.violations == []


@pytest.mark.parametrize("name, code", UNSAFE_IMPORT_SNIPPETS.items())
def test_check_blocks_unsafe_imports(name: str, code: str) -> None:
    result = safety_checker.check(code)

    assert result.is_safe is False, name
    assert result.ast_valid is True
    assert any("import" in violation.lower() for violation in result.violations)


@pytest.mark.parametrize("name, code", UNSAFE_CALL_SNIPPETS.items())
def test_check_blocks_unsafe_calls(name: str, code: str) -> None:
    result = safety_checker.check(code)

    assert result.is_safe is False, name
    assert result.ast_valid is True
    assert any("call" in violation.lower() for violation in result.violations)


def test_check_does_not_globally_block_open() -> None:
    result = safety_checker.check("with open('notes.txt', 'w') as file:\n    file.write('ok')\n")

    assert result.is_safe is True
    assert result.violations == []


@pytest.mark.parametrize("name, code", UNSAFE_OPEN_SNIPPETS.items())
def test_check_blocks_open_with_dangerous_literal_paths(
    name: str, code: str
) -> None:
    result = safety_checker.check(code)

    assert result.is_safe is False, name
    assert result.ast_valid is True
    assert any("open" in violation.lower() for violation in result.violations)


def test_check_allows_open_with_dynamic_output_path() -> None:
    code = (
        "from _snapscript_paths import OUTPUT_PATH\n"
        "with open(OUTPUT_PATH, 'w') as file:\n"
        "    file.write('ok')\n"
    )

    result = safety_checker.check(code)

    assert result.is_safe is True
    assert result.violations == []


def test_check_returns_invalid_result_for_syntax_error() -> None:
    result = safety_checker.check("for\n")

    assert result.is_safe is False
    assert result.ast_valid is False
    assert any("syntax" in violation.lower() for violation in result.violations)


def test_safety_checker_core_has_no_ui_or_execution_dependencies() -> None:
    source = Path("src/snapscript/core/safety_checker.py").read_text()

    assert "argparse" not in source
    assert "rich" not in source
    assert "streamlit" not in source
    assert "sys.argv" not in source
    assert "import subprocess" not in source
    assert "exec(" not in source
