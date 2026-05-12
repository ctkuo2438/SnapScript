# Agent Instructions

## Project
- SnapScript is a Python CLI/web tool for natural-language CSV/Excel processing.
- Phase 1 priority is the CLI pipeline. Do not start Streamlit work until 8/10 CLI gate tasks pass on first attempt.

## Commands
| Task | Command |
|------|---------|
| Sync deps | `uv sync` |
| Run app | `uv run python main.py` |
| Run tests | `uv run pytest` |
| Run one test | `uv run pytest tests/<test_file>.py` |

## References
| Need | File |
|------|------|
| Architecture | `snapscript-sds.md` |
| Active TODOs and decisions | `TODOS.md` |
| Package/dependency config | `pyproject.toml` |

## Required Skills
- Use `snapscript-phase-discipline` for features, scope decisions, roadmap changes, or dependency additions.
- Use `snapscript-module-conventions` when creating or changing `src/snapscript/` modules, dataclasses, or imports.
- Use `snapscript-safety-rules` for code generation, prompt building, AST checks, path injection, sandbox execution, or safety tests.
- Use `snapscript-claude-api-conventions` for the current Anthropic implementation in `code_generator.py`, `retry_handler.py`, API retries, model fallback, or API logging.

## Phase Discipline
- Phase 1 is CLI-first: `interfaces/cli.py`, core modules, subprocess sandbox, CSV/Excel only.
- Days 8-10 are for prompt iteration on `prompts/system.txt`; record failure modes and prompt changes.
- Phase 2 Streamlit starts only after the 8/10 no-retry CLI gate passes.
- Do not add Phase 2/3 or future-scope features while working on Phase 1 unless explicitly approved.

## Module Conventions
- Keep `src/snapscript/core/` interface-agnostic: no Streamlit, argparse/click, rich rendering, `sys.argv`, or direct UI state.
- Put CLI/web behavior under `src/snapscript/interfaces/`.
- Keep shared dataclasses in `src/snapscript/core/models.py`; import them instead of redefining.
- Core raises typed exceptions; interfaces catch and format user-facing messages.

## Safety And Sandbox
- Preserve the two-layer defense: `safety_checker` static AST scan first, `sandbox_executor` isolated execution second.
- Never trust generated code because it parsed, looked reasonable, or came from an LLM provider.
- Use `_snapscript_paths.py` for `INPUT_PATH` and `OUTPUT_PATH`; never inject paths with `str.replace()`.
- Keep `open()` allowed but constrained by AST checks for literal absolute/traversal paths.
- Validate outputs after execution by reading the first row; empty or unreadable output is failure.
- Do not log user file contents, full prompts, generated code, API keys, `.env`, or secrets.

## LLM Provider API
- Phase 1 may use Anthropic Claude as the default implementation; keep provider-specific details behind config and API wrapper code.
- Use the configured provider SDK; do not hand-roll HTTP calls.
- Keep system and user prompts separate.
- Read provider and model names from config; do not hardcode them in business logic.
- `generate(prompt, model=None)` supports fallback escalation through `config.fallback_model`.
- Use `temperature=0` for code generation and keep API retries bounded.

## Workflow
- Run `git status --short` before editing.
- Make minimal changes; do not rewrite unrelated code or generated/lock files unless required.
- Use `uv run` commands for verification and run the smallest relevant test.
- Do not commit, push, or run destructive commands unless explicitly asked.
