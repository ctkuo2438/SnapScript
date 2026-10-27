"""Reject known unsafe syntax before generated code reaches an executor.

These AST guardrails do not prove arbitrary Python safe or resolve dynamic paths.
Docker provides execution isolation; subprocess does not isolate host files.
"""

from __future__ import annotations

import ast
import re

from snapscript.config import AppConfig
from snapscript.core.models import SafetyResult


BLOCKED_IMPORTS = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "socket",
        "http",
        "urllib",
        "requests",
        "ftplib",
        "smtplib",
        "pickle",
        "shelve",
        "ctypes",
        "importlib",
        "code",
        "codeop",
    }
)

BLOCKED_CALLS = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "__import__",
        "globals",
        "locals",
        "getattr",
        "setattr",
        "delattr",
    }
)

ALLOWED_INTERNAL_IMPORTS = frozenset({"_snapscript_paths"})
BLOCKED_NAMES = BLOCKED_CALLS | {"__builtins__"}
# Import restrictions and dataframe column attributes have different meanings.
BLOCKED_ATTRIBUTES = (BLOCKED_IMPORTS - {"code", "codeop", "http", "requests"}) | {
    "urlopen", "urlretrieve",
}
BLOCKED_PATH_CALLS = frozenset({"home", "expanduser"})
PATH_CONSTRUCTORS = frozenset({"Path", "PurePath", "PurePosixPath", "PureWindowsPath"})
FILE_IO_CALLS = frozenset({"open", "ExcelFile", "ExcelWriter", "get_handle"})
IO_PATH_KEYWORDS = frozenset({
    "file", "filepath_or_buffer", "path_or_buf", "io", "excel_writer",
    "buf", "path", "fname", "path_or_buffer", "con",
})
NON_IO_CONVERSIONS = frozenset({
    "to_datetime", "to_numeric", "to_timedelta", "to_frame", "to_period", "to_timestamp",
})
URI_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def check(code: str, config: AppConfig | None = None) -> SafetyResult:
    config = config if config is not None else AppConfig()
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return SafetyResult(
            is_safe=False,
            violations=[f"Syntax error: {exc.msg}"],
            ast_valid=False,
        )

    visitor = _SafetyVisitor(config)
    visitor.visit(tree)

    return SafetyResult(
        is_safe=not visitor.violations,
        violations=visitor.violations,
        ast_valid=True,
    )


class _SafetyVisitor(ast.NodeVisitor):
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_import(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is None:
            self.violations.append("Relative imports are not allowed")
        else:
            self._check_import(node.module)
        for alias in node.names:
            self._check_attribute(alias.name)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in BLOCKED_NAMES:
            self.violations.append(f"Blocked unsafe name: {node.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._check_attribute(node.attr)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = _call_name(node.func)
        is_bare_call = isinstance(node.func, ast.Name)
        if is_bare_call and call_name in BLOCKED_CALLS:
            self.violations.append(f"Blocked unsafe call: {call_name}")
        if call_name in BLOCKED_PATH_CALLS:
            self.violations.append(f"Blocked home path access: {call_name}")
        if call_name is not None:
            self._check_io_call(node, call_name)
        self.generic_visit(node)

    def _check_attribute(self, name: str) -> None:
        if (name.startswith("__") and name != "__name__") or name in BLOCKED_ATTRIBUTES:
            self.violations.append(f"Blocked unsafe attribute: {name}")

    def _check_import(self, module_name: str) -> None:
        root_name, *attributes = module_name.split(".")
        if root_name in BLOCKED_IMPORTS:
            self.violations.append(f"Blocked unsafe import: {module_name}")
            return
        if root_name not in self._allowed_import_roots():
            self.violations.append(f"Import is not allowed: {module_name}")
        for name in attributes:
            self._check_attribute(name)

    def _allowed_import_roots(self) -> set[str]:
        return {
            module.split(".", 1)[0]
            for module in (set(self.config.allowed_imports) | ALLOWED_INTERNAL_IMPORTS)
        }

    def _check_io_call(self, node: ast.Call, name: str) -> None:
        if name in PATH_CONSTRUCTORS or name == "joinpath":
            path_args = node.args
        elif name in FILE_IO_CALLS or (
            name.startswith(("read_", "to_")) and name not in NON_IO_CONVERSIONS
        ):
            path_args = node.args[:1] + [
                keyword.value for keyword in node.keywords
                if keyword.arg in IO_PATH_KEYWORDS
            ]
        else:
            return
        for arg in path_args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if not _is_dangerous_literal_path(arg.value):
                    continue
                self.violations.append(
                    f"Blocked {name}() with unsafe literal path: {arg.value}"
                )


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_dangerous_literal_path(path_value: str) -> bool:
    return (
        "/" in path_value
        or "\\" in path_value
        or ".." in path_value
        or path_value.lstrip().startswith("~")
        or URI_SCHEME.match(path_value.lstrip()) is not None
    )
