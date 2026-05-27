import ast
import importlib.util
from pathlib import Path

import pytest

from snapscript.core import safety_checker
from snapscript.core.models import SafetyResult


_FIXTURE_PATH = Path("tests/fixtures/unit/malicious_code.py")
_SPEC = importlib.util.spec_from_file_location("malicious_code", _FIXTURE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
malicious_code = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(malicious_code)

SAFE_PANDAS_IO = malicious_code.SAFE_PANDAS_IO
SAFE_RELATIVE_OPEN = malicious_code.SAFE_RELATIVE_OPEN
SAFE_SNIPPETS = malicious_code.SAFE_SNIPPETS
UNSAFE_ABSOLUTE_OPEN = malicious_code.UNSAFE_ABSOLUTE_OPEN
UNSAFE_CALL_SNIPPETS = malicious_code.UNSAFE_CALL_SNIPPETS
UNSAFE_DYNAMIC_IMPORT_DUNDER = malicious_code.UNSAFE_DYNAMIC_IMPORT_DUNDER
UNSAFE_DYNAMIC_IMPORT_IMPORTLIB = malicious_code.UNSAFE_DYNAMIC_IMPORT_IMPORTLIB
UNSAFE_EVAL = malicious_code.UNSAFE_EVAL
UNSAFE_EXEC = malicious_code.UNSAFE_EXEC
UNSAFE_GETATTR = malicious_code.UNSAFE_GETATTR
UNSAFE_IMPORT_SNIPPETS = malicious_code.UNSAFE_IMPORT_SNIPPETS
UNSAFE_IMPORT_OS = malicious_code.UNSAFE_IMPORT_OS
UNSAFE_IMPORT_SUBPROCESS = malicious_code.UNSAFE_IMPORT_SUBPROCESS
UNSAFE_OPEN_SNIPPETS = malicious_code.UNSAFE_OPEN_SNIPPETS
UNSAFE_SHELL_OS_SYSTEM = malicious_code.UNSAFE_SHELL_OS_SYSTEM
UNSAFE_SHELL_SUBPROCESS_RUN = malicious_code.UNSAFE_SHELL_SUBPROCESS_RUN
UNSAFE_TRAVERSAL_OPEN = malicious_code.UNSAFE_TRAVERSAL_OPEN


UNSAFE_EXAMPLES = [
    ("unsafe_import_os", UNSAFE_IMPORT_OS),
    ("unsafe_import_subprocess", UNSAFE_IMPORT_SUBPROCESS),
    ("unsafe_shell_os_system", UNSAFE_SHELL_OS_SYSTEM),
    ("unsafe_shell_subprocess_run", UNSAFE_SHELL_SUBPROCESS_RUN),
    ("unsafe_dynamic_import_dunder", UNSAFE_DYNAMIC_IMPORT_DUNDER),
    ("unsafe_dynamic_import_importlib", UNSAFE_DYNAMIC_IMPORT_IMPORTLIB),
    ("unsafe_exec", UNSAFE_EXEC),
    ("unsafe_eval", UNSAFE_EVAL),
    ("unsafe_getattr", UNSAFE_GETATTR),
    ("unsafe_absolute_open", UNSAFE_ABSOLUTE_OPEN),
    ("unsafe_traversal_open", UNSAFE_TRAVERSAL_OPEN),
]


SAFE_EXAMPLES = [
    ("safe_pandas_io", SAFE_PANDAS_IO),
    ("safe_relative_open", SAFE_RELATIVE_OPEN),
]


def test_check_allows_normal_pandas_input_output_code() -> None:
    result = safety_checker.check(SAFE_PANDAS_IO)

    assert isinstance(result, SafetyResult)
    assert result.is_safe is True
    assert result.ast_valid is True
    assert result.violations == []


@pytest.mark.parametrize("name, code", UNSAFE_EXAMPLES)
def test_check_blocks_named_unsafe_regression_fixtures(
    name: str, code: str
) -> None:
    result = safety_checker.check(code)

    assert result.is_safe is False, name
    assert result.ast_valid is True
    assert result.violations


@pytest.mark.parametrize("name, code", UNSAFE_IMPORT_SNIPPETS.items())
def test_check_blocks_unsafe_import_fixtures(name: str, code: str) -> None:
    result = safety_checker.check(code)

    assert result.is_safe is False, name
    assert result.ast_valid is True
    assert any("import" in violation.lower() for violation in result.violations)


@pytest.mark.parametrize("name, code", UNSAFE_CALL_SNIPPETS.items())
def test_check_blocks_unsafe_call_fixtures(name: str, code: str) -> None:
    result = safety_checker.check(code)

    assert result.is_safe is False, name
    assert result.ast_valid is True
    assert result.violations


@pytest.mark.parametrize("name, code", UNSAFE_OPEN_SNIPPETS.items())
def test_check_blocks_unsafe_open_fixtures(name: str, code: str) -> None:
    result = safety_checker.check(code)

    assert result.is_safe is False, name
    assert result.ast_valid is True
    assert any("open" in violation.lower() for violation in result.violations)


@pytest.mark.parametrize("name, code", SAFE_EXAMPLES)
def test_check_allows_named_safe_regression_fixtures(
    name: str, code: str
) -> None:
    result = safety_checker.check(code)

    assert result.is_safe is True, name
    assert result.ast_valid is True
    assert result.violations == []


@pytest.mark.parametrize("name, code", SAFE_SNIPPETS.items())
def test_check_allows_safe_fixtures(name: str, code: str) -> None:
    result = safety_checker.check(code)

    assert result.is_safe is True, name
    assert result.ast_valid is True
    assert result.violations == []


def test_check_does_not_globally_block_open() -> None:
    result = safety_checker.check(SAFE_RELATIVE_OPEN)

    assert result.is_safe is True
    assert result.violations == []


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


def test_check_fails_safely_for_incomplete_assignment() -> None:
    result = safety_checker.check("x =")

    assert result.is_safe is False
    assert result.ast_valid is False
    assert any("syntax" in violation.lower() for violation in result.violations)


def test_safety_checker_core_has_no_ui_or_execution_dependencies() -> None:
    source = Path("src/snapscript/core/safety_checker.py").read_text()
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    called_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)

    forbidden_modules = {
        "argparse",
        "rich",
        "streamlit",
        "gradio",
        "fastapi",
        "flask",
        "dash",
        "subprocess",
        "snapscript.core.sandbox_executor",
        "snapscript.core.docker_sandbox_executor",
        "snapscript.core.execution_backend",
        "snapscript.core.retry_handler",
        "snapscript.core.code_generator",
    }

    assert imported_modules.isdisjoint(forbidden_modules)
    assert "sys.argv" not in source
    # Use AST calls here so comments or inert strings containing "exec(" do not fail.
    assert "exec" not in called_names
    assert "eval" not in called_names
