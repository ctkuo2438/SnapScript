# Agent Instructions

## Project
- SnapScript is a Python CLI/web/MCP tool for natural-language CSV/Excel processing.
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
| Architecture, Phase 1–4, active TODOs | `docs/development.md` |
| Active feature spec | `specs/csv-merge.md` |
| MCP feature spec and verification | `specs/mcp.md` |
| Feature verification | `docs/ai_csv_merge_verification.md` |
| Docker sandbox | `docs/docker_sandbox.md` |
| Package/dependency config | `pyproject.toml` |

`docs/` and `specs/` are local-only and may be absent after cloning. References to
those folders are optional; use the user's requirements and source/tests when
these notes are unavailable. Keep new plans/specifications/verification local.

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
- Preserve existing Phase 2 Streamlit behavior, except the approved Docker default (see `specs/csv-merge.md`).
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
- Use `ErrorCategory` from `core/models.py`; producers set categories. Retry policy and interface exit codes must not infer categories from diagnostic text.
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
- AST checks reject known unsafe patterns; they do not prove arbitrary Python safe. Docker is the execution isolation boundary.
- Never trust generated code because it parsed, looked reasonable, or came from an LLM provider.
- Use `_snapscript_paths.py` for path injection.
- For single-file mode, support `INPUT_PATH` and `OUTPUT_PATH`.
- For multi-file mode, support `INPUT_PATHS` and `OUTPUT_PATH`.
- Never inject paths with `str.replace()`.
- Keep `open()`, pathlib constructors and pandas I/O allowed with injected paths; reject unsafe literal paths/URLs in positional and path keyword arguments.
- Validate outputs after execution by reading the first row; empty or unreadable output is failure.
- Streamlit defaults to the Docker backend; subprocess requires an explicit `SNAPSCRIPT_SANDBOX_BACKEND=subprocess` and shows a sidebar warning. The CLI default stays subprocess; MCP requires Docker.
- Docker sandbox must mount only the per-run temporary workspace.
- Do not mount the repo root or user home into Docker.
- Do not weaken Docker runtime restrictions such as network-disabled mode, memory limits, CPU limits, or PID limits.
- Keep capability removal, no-new-privileges, read-only root, bounded `/tmp` tmpfs, non-root UID mapping, and private workspace permissions (0700 directories, 0600 copied files).
- Require `seccomp=builtin` and verify `Seccomp: 2` in a bounded, mount-free preflight before generation. Fail closed if unavailable; never change host Docker settings automatically.
- Validate the 1–30 second Docker timeout range in `AppConfig`; do not silently clamp it in interfaces/backends. Published outputs stay private (0600).
- Do not log user file contents, full prompts, generated code, API keys, `.env`, environment variables, full tracebacks, or secrets by default.

## LLM Provider API
- Anthropic Claude may remain the default implementation, but provider-specific details must stay behind config and API wrapper code.
- Use the configured provider SDK; do not hand-roll HTTP calls.
- Read credentials from the environment; the approved CLI no longer accepts `--api-key`. Detect missing resolved SDK credentials before making a request.
- Keep system and user prompts separate.
- Read provider and model names from config; do not hardcode them in business logic.
- If fallback escalation is implemented or modified, use `config.fallback_model`; do not hardcode fallback models in business logic.
- Omit sampling parameters for models that do not accept them (`temperature=None`). Use an explicit temperature only with a compatible model. Keep API timeouts and retries bounded.
- Real-provider tests must be opt-in only.

## Workflow
- Run `git status --short` before editing.
- Make minimal changes; do not rewrite unrelated code or generated/lock files unless required.
- Use `uv run` commands for verification.
- Run the smallest relevant tests first, then broader tests for gates.
- Do not commit, push, or run destructive commands unless explicitly asked.

## Spec-Driven Development
- For feature work, read the relevant local spec (`specs/csv-merge.md` for CSV Merge, `specs/mcp.md` for the approved local MCP tools) when present. If absent, establish expected behavior from the user's requirements and source/tests, and record the plan in a local spec before editing code. Consult local `docs/development.md` when available.
- Compare the spec with existing code; implement only the missing behavior.
- Keep a short implementation checklist in the spec and record routine decisions there. Use existing user authorization; do not ask again for routine implementation choices.
- Give each acceptance criterion an ID and map it to independent expected results and verification commands.
- Add meaningful regression tests, implement, run the smallest relevant tests, and fix failures before the full gate.
- Write actual command results and AC evidence to `docs/ai_csv_merge_verification.md` for CSV Merge, or `specs/mcp.md` for MCP. Mark skipped Docker/provider checks as unverified, never passed.
- The agent develops SnapScript; do not add a runtime agent framework or HTTP API just to adopt this workflow.

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
