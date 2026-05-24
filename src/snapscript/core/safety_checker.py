'''
schema_inspector.inspect(...)
  -> prompt_builder.build(...)
  -> retry_handler.run(...)
      -> code_generator.generate(...)
          -> GeneratedScript(code=...)
      -> safety_checker.check(generated.code)

code_generator.py only generates valid python syntax, but valid doesn't mean safe.
Therefore, safety_checker.py do the AST-based safety validation before executing the code, 
to catch any potentially unsafe code patterns that could cause harm if executed.

Goal: Before the code executed in subprocess or docker sandbox, make sure the code is safe enough to run
'''

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


# AST visitor that checks for unsafe imports and function calls in the generated code
class _SafetyVisitor(ast.NodeVisitor):
    def __init__(self, config: AppConfig) -> None:
        self.config = config # read allowed imports from config
        self.violations: list[str] = []

    # check import xxx
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names: # ex: pandas and os
            self._check_import(alias.name)
        self.generic_visit(node)
    
    # check from xxx import yyy
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is None:
            self.violations.append("Relative imports are not allowed")
        else:
            self._check_import(node.module)
        self.generic_visit(node)

    # check function calls, ex: pd.read_csv(), open(), eval(), exec(), etc
    def visit_Call(self, node: ast.Call) -> None:
        call_name = _call_name(node.func)
        if call_name in BLOCKED_CALLS:
            self.violations.append(f"Blocked unsafe call: {call_name}")
        if call_name == "open": # if is open() call, then do extra checks on the file path
            self._check_open_call(node)
        self.generic_visit(node)

    # check attribute access, ex: os.system, subprocess.Popen, etc
    def _check_import(self, module_name: str) -> None:
        root_name = module_name.split(".", 1)[0] # get the root module name, ex: os.path -> os
        if root_name in BLOCKED_IMPORTS:
            self.violations.append(f"Blocked unsafe import: {module_name}")
            return
        if root_name not in self._allowed_import_roots():
            self.violations.append(f"Import is not allowed: {module_name}")

    # extract the function name from a call node, ex: pd.read_csv() -> read_csv
    def _allowed_import_roots(self) -> set[str]:
        return {
            module.split(".", 1)[0]
            for module in (set(self.config.allowed_imports) | ALLOWED_INTERNAL_IMPORTS)
        }

    # check if the open() call has a literal string argument that looks like a file path, 
    #   which could be dangerous
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

# ex: pd.read_csv(INPUT_PATH) -> read_csv
def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


# check if the literal string looks like a file path that could be dangerous, 
# ex: / or ../ or ~ or C:\ etc
def _is_dangerous_literal_path(path_value: str) -> bool:
    return (
        "/" in path_value
        or ".." in path_value
        or path_value.startswith("~")
        or WINDOWS_ABSOLUTE_PATH.match(path_value) is not None
    )
