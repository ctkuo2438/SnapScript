---
name: snapscript-safety-rules
description: |
  Use when writing or modifying code in SnapScript that touches code generation,
  AST analysis, sandbox execution, or path injection. Triggers include working
  on safety_checker.py, sandbox_executor.py, prompt_builder.py system prompts,
  or tests under tests/test_safety_checker.py. Do NOT use for general Python
  coding outside SnapScript's safety perimeter.
---

# SnapScript safety rules

This skill reflects decisions in TODOS.md section "Architecture decisions".
Those decisions OVERRIDE older drafts in snapscript-sds.md where they conflict.

## Two layers of defense — never collapse to one

safety_checker (AST scan) is the first line of defense.
sandbox_executor (process isolation) is the second line of defense.

Both must exist. safety_checker alone is bypassable via dynamic strings
(string concatenation, getattr lookup). sandbox_executor alone wastes API
tokens generating code that should be rejected at parse time.

## PATH injection: _snapscript_paths.py (NOT str.replace)

Per TODOS.md decision: sandbox_executor writes _snapscript_paths.py to the
tempdir. Generated scripts import paths from it.

The generated script does this:

    from _snapscript_paths import INPUT_PATH, OUTPUT_PATH

sandbox_executor writes tempdir/_snapscript_paths.py with content like:

    INPUT_PATH = "/abs/path/to/copied_input.csv"
    OUTPUT_PATH = "/abs/path/to/output.csv"

DO NOT use code.replace("INPUT_PATH", actual_path). It is brittle (matches
inside string literals and comments) and is an explicit anti-pattern in
this project.

## open() is ALLOWED — but constrained

Earlier draft had open in BLOCKED_CALLS. This was changed.

Allowed usage:
- open("relative_name.txt") — relative path is OK
- open(OUTPUT_PATH, "w") — injected path is OK
- open(some_variable) — dynamic argument; AST allows, sandbox contains

AST blocks (literal string argument matching):
- open("/etc/passwd") — absolute path
- open("../../secret") — path traversal
- open("C:\\Windows\\System32\\foo") — absolute Windows path

The check: AST visits Call(func=Name(id="open")). If args[0] is a
Constant(str), validate the string. Dynamic arguments fall through to the
sandbox path containment.

## Blocked imports

Block these at AST parse time:

    BLOCKED_IMPORTS = {
        "os", "sys", "subprocess", "shutil",
        "socket", "http", "urllib", "requests", "ftplib", "smtplib",
        "pickle", "shelve",
        "ctypes", "importlib",
        "code", "codeop",
    }

compile and compileall are functions, not imports — they are covered under
BLOCKED_CALLS below.

## Blocked function calls

    BLOCKED_CALLS = {
        "exec", "eval", "compile", "__import__",
        "globals", "locals",
        "getattr", "setattr", "delattr",
    }

NOTE: open is NOT in BLOCKED_CALLS — see "open() is ALLOWED" above.

## Allowed imports (whitelist per AppConfig)

    ALLOWED_IMPORTS = frozenset({
        "pandas", "pd",
        "openpyxl",
        "csv", "json", "re", "datetime", "pathlib",
        "collections", "itertools", "functools",
        "math", "decimal",
        "typing",
    })

When adding a new allowed import, justify in the PR description WHY a
malicious script cannot abuse it. Default answer is NO.

## Prompt-injection defense (schema in <schema> delimiters)

Per TODOS.md: prompt_builder MUST wrap schema in delimiters so an attacker
naming a column "\nIgnore previous instructions..." cannot escape:

    user_prompt = f"""
    ## Input file information
    <schema>
    {rendered_schema}
    </schema>

    ## Task description
    {user_task_description}
    """

Plus: column names truncated to 100 chars in schema_inspector before they
reach the prompt.

## Output validation (post-execution)

Per TODOS.md: sandbox_executor MUST read the first row of the output file
after subprocess.run returns. Empty or unreadable output means
ExecutionResult(success=False).

At end of sandbox_executor.execute():

    try:
        if output_path.exists():
            if output_path.suffix == ".csv":
                pd.read_csv(output_path, nrows=1)
            elif output_path.suffix in (".xlsx", ".xls"):
                pd.read_excel(output_path, nrows=1)
        else:
            return ExecutionResult(success=False, ...)
    except Exception as e:
        return ExecutionResult(
            success=False,
            stderr=f"Output unreadable: {e}",
            ...
        )

A script that ran cleanly but produced nothing is a FAILURE.

## When writing tests for safety_checker

Cover BOTH directions in tests/test_safety_checker.py.

Positive tests (block known-bad):
- import os, import subprocess
- __import__("os"), __import__("o" + "s")
- exec(user_input), eval("...")
- getattr(__builtins__, "exec")(code)
- open("/etc/passwd"), open("../../secret")

Negative tests (allow legitimate):
- import pandas as pd
- pd.read_csv(INPUT_PATH)
- df.to_csv(OUTPUT_PATH, index=False)
- open("relative.txt", "w")
- Long pandas chains shouldn't false-positive

Use tests/fixtures/malicious_code.py as the registry of known-bad patterns.

## Privacy: never log file content

NEVER:
- logger.info(f"Processing {df.head()}")
- logger.info(f"Prompt: {full_prompt}")
- logger.info(f"Generated: {code}")

OK:
- logger.info(f"File: name={filename}, rows={n}, cols={k}")
- logger.info(f"API: model={m}, in={ti}, out={to}, ms={lat}")
- logger.info(f"Generated {len(code)} chars")

## When tempted to weaken a check

False positives mean the user rephrases their task — recoverable.
False negatives mean a compromised machine — NOT recoverable.

If a check feels too strict, the right move is usually to add a narrow
whitelist for the specific legitimate pattern, not weaken the general rule.
