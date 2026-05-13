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
WINDOWS_ABSOLUTE_PATH = re.compile(r"^[a-zA-Z]:[\\/]")


def check(code: str) -> SafetyResult:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return SafetyResult(
            is_safe=False,
            violations=[f"Syntax error: {exc.msg}"],
            ast_valid=False,
        )

    visitor = _SafetyVisitor(AppConfig())
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
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = _call_name(node.func)
        if call_name in BLOCKED_CALLS:
            self.violations.append(f"Blocked unsafe call: {call_name}")
        if call_name == "open":
            self._check_open_call(node)
        self.generic_visit(node)

    def _check_import(self, module_name: str) -> None:
        root_name = module_name.split(".", 1)[0]
        if root_name in BLOCKED_IMPORTS:
            self.violations.append(f"Blocked unsafe import: {module_name}")
            return
        if root_name not in self._allowed_import_roots():
            self.violations.append(f"Import is not allowed: {module_name}")

    def _allowed_import_roots(self) -> set[str]:
        return {
            module.split(".", 1)[0]
            for module in (set(self.config.allowed_imports) | ALLOWED_INTERNAL_IMPORTS)
        }

    def _check_open_call(self, node: ast.Call) -> None:
        if not node.args:
            return
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            path_value = first_arg.value
            if _is_dangerous_literal_path(path_value):
                self.violations.append(
                    f"Blocked open() with unsafe literal path: {path_value}"
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
        or ".." in path_value
        or path_value.startswith("~")
        or WINDOWS_ABSOLUTE_PATH.match(path_value) is not None
    )
