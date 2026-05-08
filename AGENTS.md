# AGENTS.md

## Project: SnapScript

SnapScript is a CLI/web tool that lets users describe data processing tasks in natural language, auto-generates Python scripts, and executes them in a local sandbox.

The MVP focuses on CSV/Excel processing.

## Tech Stack

- Python
- LLM API integration
- pandas
- Streamlit for Phase 2
- uv for dependency and command management

Full system design document: see `snapscript-sds.md`.

## Working Rules

- Read `README.md`, `snapscript-sds.md`, `pyproject.toml`, and relevant source files before making major changes.
- Make minimal, targeted changes that fit the existing architecture.
- Do not rewrite unrelated code.
- Do not add new dependencies unless necessary.
- Do not modify generated files, lock files, or configuration files unless the task requires it.
- Do not commit or push changes unless explicitly asked.
- Before editing, explain the intended approach briefly when the task is non-trivial.

## Dev Environment

Use `uv run` instead of `pip install` plus `python`.

All dependencies are managed by `uv`.

Preferred commands:

- Install/sync dependencies: `uv sync`
- Run app: `uv run python main.py`
- Run tests: `uv run pytest`
- Run a specific test: `uv run pytest tests/<test_file>.py`

## Python Coding Guidelines

- Follow the existing project structure and naming style.
- Keep functions focused and easy to test.
- Prefer explicit type hints where they improve clarity.
- Use clear error messages for user-facing CLI or script execution failures.
- Keep sandbox execution logic conservative and safe.
- Avoid broad exception swallowing unless the error is intentionally converted into a user-facing message.

## Data Processing Guidelines

- Prioritize CSV/Excel workflows for the MVP.
- Use pandas idiomatically.
- Validate input file paths and extensions before processing.
- Preserve user data unless the user explicitly requests modification.
- Prefer writing outputs to clearly named generated/output paths rather than overwriting source files.
- When generating Python scripts, keep them readable, deterministic, and easy to inspect.

## Sandbox and Safety Rules

- Never execute destructive commands without explicit approval.
- Do not access secrets, credentials, `.env` files, API keys, or private tokens unless explicitly requested.
- Do not send local user data to external services unless the task clearly requires it and the user has approved the behavior.
- Generated scripts should avoid network access, shell execution, file deletion, or unrestricted filesystem access unless explicitly required.
- If sandbox behavior is unclear, stop and explain the risk before changing it.

## Verification

After code changes, run the smallest relevant verification command.

Preferred order:

1. Run targeted tests if the changed area has tests.
2. Run the full test suite if practical.
3. Run the CLI manually with a small sample input if tests are not available.

Use `uv run pytest` for the full test suite.

Before finishing, summarize:

- Files changed
- What changed
- What was verified
- Any remaining risks or TODOs

## Project Workflow

When asked to implement a feature:

1. Inspect the current codebase.
2. Identify the relevant files.
3. Propose a minimal plan.
4. Implement the change.
5. Run relevant tests or commands.
6. Summarize the result.

When asked to debug:

1. Reproduce or inspect the error.
2. Read the stack trace carefully.
3. Identify the smallest likely root cause.
4. Make a minimal fix.
5. Re-run the failing command.

## Git Safety

- Run `git status` before making changes when editing files.
- Review `git diff` before summarizing changes.
- Do not commit unless explicitly asked.
- Do not push unless explicitly asked.
- Do not run destructive Git commands unless explicitly approved.

## Communication Style

- Be concise and specific.
- Explain technical tradeoffs when relevant.
- Prefer actionable steps over broad explanations.
- If something is uncertain, state the uncertainty and verify through files or commands.

## Project-Specific Skills

This project has 4 skills under `.codex/skills/`:
- `snapscript-safety-rules` — security model and AST checks
- `snapscript-module-conventions` — module structure and dataclasses
- `snapscript-claude-api-conventions` — Claude API usage rules
- `snapscript-phase-discipline` — what belongs in Phase 1/2/3

Skills load progressively when relevant. They reflect decisions captured in
`TODOS.md` § "Architecture decisions" — read that section before assuming
defaults from `snapscript-sds.md`.

## Decision Log

`TODOS.md` § "Architecture decisions" supersedes `snapscript-sds.md` where
they conflict. Notable decisions:

- **PATH injection via `_snapscript_paths.py`** — NOT `str.replace()` on code
- **`open()` is allowed** but checked for absolute/traversal paths in AST
- **Output validation** — sandbox reads first row of output file post-execution
- **Schema delimiters** — `<schema>...</schema>` wraps schema in prompts (prompt-injection defense)
- **Column name truncation** — 100 chars max in schema_inspector

When implementing, ALWAYS check TODOS.md before falling back to SDS defaults.

## Roadmap Reality

Per TODOS.md, the timeline is **30 days, not 8**:
- Days 1-10: CLI pipeline
- Days 8-10: dedicated prompt iteration (gate: 8/10 CLI tasks pass without retry)
- Days 11-25: Streamlit
- Days 26-30: user observation

Don't rush Phase 2 before the CLI prompt-iteration gate passes.
