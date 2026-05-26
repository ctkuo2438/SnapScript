# Agent Instructions

## Project
- SnapScript is a Python CLI/web tool for natural-language CSV/Excel processing.
- Phase 1 built the single-file CLI/core pipeline.
- Phase 2 added a thin Streamlit UI on top of the same safe core pipeline.
- Phase 3 added Docker sandbox hardening and an execution backend router.
- Current roadmap focus: Phase 4A Multi-file Input Support.
- Phase 4A should add two-file CSV/Excel workflows while preserving single-file backward compatibility.

## Commands
| Task | Command |
|------|---------|
| Sync deps | `uv sync` |
| Run app | `uv run python main.py` |
| Run Streamlit | `uv run streamlit run app.py` |
| Run tests | `uv run pytest` |
| Run one test | `uv run pytest tests/<test_file>.py` |

## References
| Need | File |
|------|------|
| Architecture | `snapscript-sds.md` |
| Active TODOs and decisions | `TODOS.md` |
| Phase 1 plan | `docs/phase1_implementation_plan.md` |
| Phase 2 plan | `docs/phase2_implementation_plan.md` |
| Phase 3 plan | `docs/phase3_implementation_plan.md` |
| Phase 4 plan | `docs/phase4_implementation_plan.md` |
| Docker sandbox | `docs/docker_sandbox.md` |
| Package/dependency config | `pyproject.toml` |

## Required Skills
- Use `snapscript-phase-discipline` for features, scope decisions, roadmap changes, or dependency additions.
- Use `snapscript-module-conventions` when creating or changing `src/snapscript/` modules, dataclasses, or imports.
- Use `snapscript-safety-rules` for code generation, prompt building, AST checks, path injection, sandbox execution, Docker sandbox behavior, or safety tests.
- Use `snapscript-claude-api-conventions` for the current Anthropic implementation in `code_generator.py`, `retry_handler.py`, API retries, model fallback, or API logging.

## Phase Discipline
- Current active phase: Phase 4A Multi-file Input Support.
- Phase 4A is limited to two-file CSV/Excel workflows.
- Do not implement unlimited multi-file support unless explicitly approved.
- Do not add database connectors, cloud execution, auth, billing, dashboards, or persistent project history.
- Preserve existing Phase 1 single-file CLI behavior.
- Preserve existing Phase 2 Streamlit behavior.
- Preserve existing Phase 3 sandbox backend router and Docker hardening behavior.
- Normal `uv run pytest` must not require provider credentials.
- Normal `uv run pytest` must not require Docker.
- Real-provider tests must stay explicit opt-in with `SNAPSCRIPT_REAL_PROVIDER=1`.
- Docker-specific verification must stay explicit or be skipped unless Docker is available.

## Module Conventions
- Keep `src/snapscript/core/` interface-agnostic: no Streamlit, argparse/click, rich rendering, `sys.argv`, or direct UI state.
- Put CLI/web behavior under `src/snapscript/interfaces/`.
- Keep shared dataclasses in `src/snapscript/core/models.py`; import them instead of redefining.
- Core raises typed exceptions; interfaces catch and format user-facing messages.
- CLI and Streamlit must stay thin interface layers.
- Interfaces should collect inputs and call the approved core pipeline, not duplicate transformation logic.

## Phase 4A Multi-file Rules
- Design Phase 4A as multi-file input support, not only “merge two CSV files.”
- Phase 4A implementation should initially support at most two input files.
- Use named input files for multi-file mode, such as:
  - `orders=orders.csv`
  - `products=products.csv`
- Preserve single-file compatibility with the existing `--file input.csv` flow.
- For multi-file generated code, use:
  - `INPUT_PATHS`
  - `OUTPUT_PATH`
- Preserve `INPUT_PATH` for single-file backward compatibility.
- Extend `_snapscript_paths.py`; do not replace it with string substitution.
- Do not inject real user paths into prompts or generated code.
- Do not parse natural-language join keywords such as `inner`, `left`, `right`, or `outer` in SnapScript business logic.
- The LLM should interpret the user task and generate pandas code.
- SnapScript should provide named schemas, safe path variables, safety checks, sandbox execution, and output validation.

## Safety And Sandbox
- Preserve the two-layer defense: `safety_checker` static AST scan first, sandbox execution second.
- Never trust generated code because it parsed, looked reasonable, or came from an LLM provider.
- Use `_snapscript_paths.py` for path injection.
- For single-file mode, support `INPUT_PATH` and `OUTPUT_PATH`.
- For multi-file mode, support `INPUT_PATHS` and `OUTPUT_PATH`.
- Never inject paths with `str.replace()`.
- Keep `open()` allowed but constrained by AST checks for literal absolute/traversal paths.
- Validate outputs after execution by reading the first row; empty or unreadable output is failure.
- Docker sandbox must mount only the per-run temporary workspace.
- Do not mount the repo root or user home into Docker.
- Do not weaken Docker runtime restrictions such as network-disabled mode, memory limits, CPU limits, or PID limits.
- Do not log user file contents, full prompts, generated code, API keys, `.env`, environment variables, full tracebacks, or secrets by default.

## LLM Provider API
- Anthropic Claude may remain the default implementation, but provider-specific details must stay behind config and API wrapper code.
- Use the configured provider SDK; do not hand-roll HTTP calls.
- Keep system and user prompts separate.
- Read provider and model names from config; do not hardcode them in business logic.
- If fallback escalation is implemented or modified, use `config.fallback_model`; do not hardcode fallback models in business logic.
- Use `temperature=0` for code generation and keep API retries bounded.
- Real-provider tests must be opt-in only.

## Workflow
- Run `git status --short` before editing.
- Make minimal changes; do not rewrite unrelated code or generated/lock files unless required.
- Use `uv run` commands for verification.
- Run the smallest relevant tests first, then broader tests for gates.
- Do not commit, push, or run destructive commands unless explicitly asked.

## Code Review Rules

When reviewing code, flag the following:

- Functions longer than 50 lines, unless the length is clearly justified.
- Abstractions that are only used once and do not improve readability.
- Speculative features not required by the current task.
- Dead code, unused imports, unused variables, and stale comments.
- Repeated test fixtures or fake classes that could be shared.
- Code paths that duplicate validation/business logic already owned by core modules.
- Cases where 200 lines could reasonably be 50 without losing clarity.
- Ask: would a senior engineer say this is overcomplicated?

Review mode rule:
- If asked to review, report findings first.
- Do not rewrite code unless explicitly asked.
- Prefer small, scoped cleanup patches over broad rewrites.