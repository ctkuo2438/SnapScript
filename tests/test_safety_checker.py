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
    if name == "attribute_eval":
        assert "Blocked unsafe name: __builtins__" in result.violations


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


def test_check_allows_re_compile_attribute_call() -> None:
    code = (
        "import re\n"
        "pattern = re.compile(r'[0-9]+')\n"
    )

    result = safety_checker.check(code)

    assert result.is_safe is True
    assert result.violations == []


def test_check_allows_pandas_eval_method_call() -> None:
    code = (
        "import pandas as pd\n"
        "df = pd.DataFrame({'price': [10], 'qty': [2]})\n"
        "df = df.eval('total = price * qty')\n"
    )

    result = safety_checker.check(code)

    assert result.is_safe is True
    assert result.violations == []


def test_check_blocks_bare_eval_call() -> None:
    result = safety_checker.check("eval('1 + 1')\n")

    assert result.is_safe is False
    assert "Blocked unsafe call: eval" in result.violations


def test_check_blocks_bare_compile_call() -> None:
    result = safety_checker.check("compile('x', '<s>', 'eval')\n")

    assert result.is_safe is False
    assert "Blocked unsafe call: compile" in result.violations


def test_check_blocks_open_with_traversal_path() -> None:
    result = safety_checker.check("open('../secret.txt')\n")

    assert result.is_safe is False
    assert "Blocked open() with unsafe literal path: ../secret.txt" in result.violations


def test_check_blocks_builtins_aliasing() -> None:
    code = (
        "b = __builtins__\n"
        "b.eval('1 + 1')\n"
    )

    result = safety_checker.check(code)

    assert result.is_safe is False
    assert "Blocked unsafe name: __builtins__" in result.violations


@pytest.mark.parametrize("name", [
    "eval", "exec", "compile", "__import__", "globals", "locals",
    "getattr", "setattr", "delattr",
])
def test_check_blocks_unsafe_names_used_as_values(name: str) -> None:
    result = safety_checker.check(f"callback = {name}\n")

    assert result.ast_valid
    assert not result.is_safe
    assert f"Blocked unsafe name: {name}" in result.violations


@pytest.mark.parametrize("code", [
    pytest.param("value.__class__", id="class-attribute"),
    pytest.param("().__class__.__base__.__subclasses__()", id="introspection-chain"),
    pytest.param("handler.__globals__", id="function-globals"),
    pytest.param("handler.__code__", id="function-code"),
    pytest.param("value.__getattribute__('__class__')", id="dunder-getattribute"),
    pytest.param("pd.io.common.os.system('true')", id="pandas-os"),
    pytest.param("pd.io.common.sys.modules", id="pandas-sys"),
    pytest.param("pd.io.common.subprocess.run(['true'])", id="pandas-subprocess"),
    pytest.param("from pandas.io.common import os as helper", id="from-import-module"),
    pytest.param("from pandas import __builtins__ as helper", id="from-import-dunder"),
])
def test_check_blocks_unsafe_attribute_access(code: str) -> None:
    result = safety_checker.check(code)

    assert result.ast_valid
    assert not result.is_safe
    assert result.violations


@pytest.mark.parametrize("code", [
    pytest.param("open(file='/etc/passwd')", id="open-keyword"),
    pytest.param("pd.read_csv('/etc/passwd')", id="pandas-absolute-read"),
    pytest.param("pd.read_csv(filepath_or_buffer='/etc/passwd')", id="pandas-read-keyword"),
    pytest.param("pd.read_excel(io='/opt/private.xlsx')", id="excel-read-keyword"),
    pytest.param("pd.ExcelFile('/etc/private.xlsx')", id="excel-file-constructor"),
    pytest.param("pd.ExcelWriter('/tmp/out.xlsx')", id="excel-writer-constructor"),
    pytest.param("pd.ExcelWriter(path='/tmp/out.xlsx')", id="excel-writer-keyword"),
    pytest.param("pd.read_csv('https://example.invalid/in.csv')", id="https-read"),
    pytest.param("pd.read_csv('ftp://example.invalid/in.csv')", id="ftp-read"),
    pytest.param("pd.read_csv('file:///etc/passwd')", id="file-url-read"),
    pytest.param("pd.read_csv('data:text/csv,value')", id="data-url-read"),
    pytest.param("pd.read_csv('s3:private.csv')", id="scheme-without-slashes"),
    pytest.param("df.to_csv('/tmp/result.csv')", id="pandas-absolute-write"),
    pytest.param("df.to_csv(path_or_buf='s3://bucket/out.csv')", id="pandas-write-keyword"),
    pytest.param("df.to_excel(excel_writer='/mnt/out.xlsx')", id="excel-write-keyword"),
    pytest.param("df.to_json(path_or_buf='../out.json')", id="json-traversal-write"),
    pytest.param("df.to_html(buf='https://example.invalid/out.html')", id="html-write-keyword"),
    pytest.param("Path('/etc/passwd').open()", id="path-open-receiver"),
    pytest.param("pathlib.Path('safe', '..', 'private.csv')", id="path-traversal-component"),
    pytest.param("Path('safe', '/etc/passwd')", id="path-absolute-component"),
    pytest.param("pd.read_csv(" + repr(r"C:\private\input.csv") + ")", id="windows-absolute"),
    pytest.param("pd.read_csv(" + repr(r"\\server\share\input.csv") + ")", id="windows-unc"),
    pytest.param("Path(" + repr(r"\private.csv") + ")", id="windows-rooted"),
    pytest.param("pd.io.common.get_handle('https://example.invalid/data.csv', 'r')", id="get-handle-url"),
    pytest.param("pd.io.common.get_handle('/etc/passwd', 'r')", id="get-handle-absolute"),
    pytest.param("pd.io.common.get_handle(path_or_buf='../secret.csv', mode='r')", id="get-handle-keyword"),
])
def test_check_blocks_unsafe_literal_io_paths(code: str) -> None:
    result = safety_checker.check(code)

    assert result.ast_valid
    assert not result.is_safe
    assert any("literal path" in violation for violation in result.violations)


@pytest.mark.parametrize("code", [
    "open(file=OUTPUT_PATH, mode='w')",
    "pd.read_csv(filepath_or_buffer=INPUT_PATH)",
    "pd.read_excel(io=INPUT_PATHS['orders'])",
    "df.to_csv(path_or_buf=OUTPUT_PATH, index=False)",
    "df.to_excel(excel_writer=OUTPUT_PATH, index=False)",
    "pd.ExcelFile(INPUT_PATH)",
    "pd.ExcelWriter(path=OUTPUT_PATH)",
    "from pathlib import Path\nPath('notes.txt').open('w')",
    "Path(INPUT_PATH).open()",
    "pd.read_csv(INPUT_PATH, sep='/')",
    "df.to_csv(OUTPUT_PATH, date_format='%Y/%m/%d')",
    "pd.to_datetime('2026/10/26')",
    "series.to_frame('amount/usd')",
    "df['__class__'] = df['os']",
    "pd.io.common.get_handle(INPUT_PATH, 'r')",
    "pd.io.common.get_handle(path_or_buf=OUTPUT_PATH, mode='w')",
])
def test_check_allows_legitimate_io_and_data_methods(code: str) -> None:
    result = safety_checker.check(code)

    assert result.ast_valid
    assert result.is_safe
    assert result.violations == []


def test_check_allows_name_dunder() -> None:
    code = (
        "from _snapscript_paths import OUTPUT_PATH\n"
        "if __name__ == '__main__':\n"
        "    open(OUTPUT_PATH, 'w').write('ok')\n"
    )

    result = safety_checker.check(code)

    assert result.is_safe is True
    assert result.violations == []


def test_check_returns_invalid_result_for_syntax_error() -> None:
    result = safety_checker.check("for\n")

    assert result.is_safe is False
    assert result.ast_valid is False
    assert any("syntax" in violation.lower() for violation in result.violations)


@pytest.mark.parametrize("code", [
    "df.code.str.upper()", "df.requests.sum()", "df.http", "df.codeop",
    "type(e).__name__", "df.home.str.upper()", "df['url'].str.startswith('https://')",
    "df['url'].eq('http://example.invalid')",
])
def test_check_allows_ordinary_attributes_and_url_data(code: str) -> None:
    assert safety_checker.check(code).is_safe


@pytest.mark.parametrize("code", [
    "pd.io.common.urlopen('http://example.invalid')",
    "opener = pd.io.common.urlopen",
    "from pandas.io.common import urlopen as opener",
    "Path.home().joinpath('private.csv').read_text()",
    "Path(INPUT_PATH).expanduser()",
    "Path(INPUT_PATH).joinpath('/etc/passwd').read_text()",
    "Path(INPUT_PATH).joinpath('..', 'private.csv').open()",
    "Path(INPUT_PATH).joinpath('https://example.invalid')",
])
def test_check_blocks_network_home_and_literal_joinpath(code: str) -> None:
    result = safety_checker.check(code)
    assert result.ast_valid
    assert not result.is_safe


@pytest.mark.parametrize("backend", ["subprocess", "docker"])
@pytest.mark.parametrize("code", [
    "pd.io.common.urlopen('http://example.invalid')", "Path.home()",
    "Path(INPUT_PATH).expanduser()", "Path(INPUT_PATH).joinpath('/etc/passwd')",
])
def test_unsafe_entrypoints_never_execute(tmp_path, monkeypatch, backend, code):
    from unittest.mock import Mock
    from snapscript.config import AppConfig
    from snapscript.core import code_generator, execution_backend, retry_handler
    from snapscript.core.models import GeneratedScript, PromptPayload

    source = tmp_path / "input.csv"
    source.write_text("value\n1\n")
    generator = Mock(return_value=GeneratedScript(code, code, "fixture"))
    executor = Mock()
    monkeypatch.setattr(code_generator, "generate", generator)
    monkeypatch.setattr(execution_backend, "preflight", lambda config: None)
    monkeypatch.setattr(execution_backend, "execute", executor)
    result = retry_handler.run(PromptPayload("system", "Copy"), source, tmp_path / "out.csv", config=AppConfig(sandbox_backend=backend))
    assert result.error_category == "safety_violation"
    generator.assert_called_once()
    executor.assert_not_called()


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
