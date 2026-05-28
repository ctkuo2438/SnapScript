# Phase 4B Prompt Assistant / Task Rewrite Implementation Plan

> Recommended workflow: implement tasks incrementally and verify each task before moving to the next. Phase 4B improves task quality before code generation and does not change the safe execution pipeline.

**Goal:** Help users write clearer CSV/Excel transformation tasks for single-file and two-file workflows, reducing ambiguous prompts that lead to poor generated pandas code.

**Architecture:** Phase 4B adds a Prompt Assistant layer before code generation. Rule-based advice runs locally with no provider call, and optional AI task rewriting happens only after an explicit user action through a core helper. The actual transformation still flows through `prompt_builder`, `code_generator`, `safety_checker`, `execution_backend`, sandbox execution, output validation, and retry handling.

**Tech Stack:** Python 3.10+, uv, pandas, existing SnapScript core modules, Streamlit, pytest, and the configured LLM provider boundary for explicit task rewrite calls.

---

## 1. Phase 4B Goals

- Help users write clearer CSV/Excel transformation tasks.
- Support both single-file and two-file workflows.
- Reduce ambiguous prompts that can lead to bad generated pandas code.
- Add non-blocking rule-based guidance.
- Add optional AI task rewriting after an explicit user click.
- Keep Generate as the only action that produces pandas code, executes sandboxed code, creates output files, or exposes preview/download results.
- Preserve all Phase 4A single-file and two-file behavior.

Phase 4B has two levels:

1. Level 1: Rule-based Prompt Coach
   - No LLM call.
   - Runs locally and cheaply.
   - Detects vague or incomplete task descriptions.
   - Shows missing details and suggestions.
   - Does not block Generate.
   - Does not execute code.
   - Does not generate pandas code.

2. Level 2: LLM-based Task Rewrite
   - Runs only after the user explicitly clicks an "Improve task with AI" action.
   - Calls a core helper, not Anthropic or provider SDKs directly from Streamlit.
   - Rewrites the natural-language task only.
   - Does not generate pandas code.
   - Does not execute sandboxed code.
   - Does not create output files.
   - Requires the user to review or use the rewritten task before pressing Generate.

## 2. Architecture

Target Phase 4B flow:

```text
CLI / Streamlit
  -> collect file(s) and task text
  -> schema_inspector.inspect(...) or inspect_many(...)
  -> task_advisor.advise_task(...)
      -> rule-based advice, no provider call
  -> optional task_rewriter.rewrite_task(...)
      -> provider-backed rewrite only after explicit user action
  -> user reviews/edits final task
  -> Generate
      -> prompt_builder
      -> code_generator
      -> safety_checker
      -> execution_backend
      -> sandbox execution
      -> output validation
```

Prompt Assistant improves task text. It does not execute transformations, generate pandas code, replace `retry_handler`, or replace `execution_backend`.

Existing Generate flow remains authoritative:

```text
prompt_builder
  -> code_generator
  -> safety_checker
  -> execution_backend
  -> sandbox execution
  -> output validation
  -> retry handling
```

Architecture boundaries:

- `src/snapscript/core/` must remain interface-agnostic.
- Core must not import Streamlit, argparse, rich, click, or UI state.
- Streamlit may call core helpers.
- Streamlit must not directly call Anthropic or any provider SDK.
- Prompt Assistant must not bypass `prompt_builder`, `code_generator`, `safety_checker`, `execution_backend`, sandbox execution, or output validation.
- Prompt Coach warnings must not block Generate.
- Do not implement a natural-language parser for joins.
- Do not synthesize merge or join code in Streamlit or CLI.
- Do not add a relational query planner.
- Normal `uv run pytest` must not require provider credentials.
- Normal `uv run pytest` must not require Docker.
- Real-provider tests must remain opt-in only.

## 3. Non-goals

Phase 4B does not include:

- Blocking Generate based on prompt quality.
- Parsing natural-language join instructions into custom SnapScript logic.
- Implementing merge or join logic in Streamlit or CLI.
- Creating a query planner.
- Changing sandbox behavior.
- Weakening `safety_checker`.
- Adding unlimited multi-file support.
- Calling a provider on upload, text change, or page load.
- Including real-provider tests in normal `uv run pytest`.
- Logging raw uploaded datasets, full prompts, generated code, API keys, `.env` contents, environment variables, secrets, or full tracebacks by default.
- Adding cloud execution, auth, billing, database connectors, dashboards, persistent project history, or hosted deployment.

## 4. Current Project History

Phase 1 built the safe CLI/core pipeline:

```text
schema inspection
  -> prompt building
  -> code generation
  -> safety checking
  -> sandbox execution
  -> output validation
  -> retry handling
```

Phase 2 added Streamlit as a thin UI:

```text
Streamlit UI
  -> upload/task validation
  -> rate limiting
  -> schema_inspector.inspect(...)
  -> prompt_builder.build(...)
  -> retry_handler.run(...)
  -> safety_checker.check(...)
  -> execution_backend.execute(...)
  -> preview/download
  -> safe audit event
```

Phase 3 added Docker sandbox hardening and execution backend routing:

```text
retry_handler.run(...)
  -> code_generator.generate(...)
  -> safety_checker.check(...)
  -> execution_backend.execute(...)
      -> subprocess sandbox
      -> Docker sandbox
```

Phase 4A added named two-file CSV/Excel input support while preserving single-file compatibility:

```text
single-file generated code
  -> INPUT_PATH and OUTPUT_PATH

two-file generated code
  -> INPUT_PATHS and OUTPUT_PATH
```

Phase 4B must improve user task quality before code generation without changing the safe execution pipeline.

## 5. Proposed File Structure

This plan task only creates `docs/phase4b_implementation_plan.md`. Future implementation will likely touch these files:

Rule-based advisor:

- Create: `src/snapscript/core/task_advisor.py`
- Create: `tests/test_task_advisor.py`
- Optional modify: `src/snapscript/core/models.py` if shared dataclasses belong there.

LLM task rewrite helper:

- Create: `src/snapscript/core/task_rewriter.py`
- Create: `src/snapscript/prompts/task_rewrite.txt`
- Create: `tests/test_task_rewriter.py`
- Optional modify: `src/snapscript/core/models.py`

Streamlit UI:

- Modify: `src/snapscript/interfaces/web.py`
- Modify: `tests/test_streamlit_app.py`
- Modify: `tests/test_streamlit_pipeline_integration.py`

Optional integration and audit work:

- Optional create: `tests/integration/test_task_rewriter_real_provider.py`
- Optional modify: `src/snapscript/core/audit_logger.py`
- Optional create: `tests/test_task_rewrite_audit.py`

Do not create these files before their associated task. Each task should stay independently reviewable.

## 6. User Experience Design

Example Streamlit UI:

```text
Task description:
[text area]

Prompt Coach
Status: Needs more detail

Missing details:
- Join key
- Join type
- Which file should keep all rows

Suggested task:
Merge orders and products using the pid column with a left join.
Keep all rows from orders and include product_name from products.

[Use suggested task] [Improve task with AI]

[Generate]
```

Rules:

- "Use suggested task" only updates `task_text`.
- "Improve task with AI" only rewrites task text.
- "Generate" remains the only action that runs the transformation pipeline.
- Prompt Coach warnings do not block Generate.
- Prompt Coach does not call the provider.
- AI Rewrite does not create output preview or download bytes.
- AI Rewrite does not automatically run Generate.

## 7. Phase 4B Task List

| Task | Status |
|------|--------|
| Task 51: Rule-based Task Advisor Core | Planned |
| Task 52: Streamlit Prompt Coach UI | Planned |
| Task 53: LLM Task Rewrite Core Helper | Planned |
| Task 54: Streamlit AI Rewrite Button | Planned |
| Task 55: Rewrite Rate Limit, Audit, and Error Rules | Planned |
| Task 56: Prompt Assistant Tests | Planned |
| Task 57: Phase 4B Gate | Planned |

## 8. Task-by-task Details

### Task 51: Rule-based Task Advisor Core

**Goal:** Add an interface-agnostic task advisor that detects vague or incomplete task descriptions.

**Likely files:**

- Create: `src/snapscript/core/task_advisor.py`
- Create: `tests/test_task_advisor.py`
- Optional modify: `src/snapscript/core/models.py` if shared dataclasses belong there.

Suggested dataclass:

```python
@dataclass(frozen=True)
class TaskAdvice:
    quality: Literal["good", "needs_detail", "too_vague"]
    missing_details: list[str]
    suggestions: list[str]
    suggested_task: str | None
```

Suggested API:

```python
def advise_task(
    task_text: str,
    schema: SchemaReport | MultiFileSchemaReport,
) -> TaskAdvice:
    ...
```

Design notes:

- No provider calls.
- No code generation.
- No sandbox execution.
- Deterministic and easy to test.
- Works for single-file and two-file schemas.
- Uses logical file names from `MultiFileSchemaReport` where available.
- Does not silently rewrite `task_text`.
- Does not block Generate.
- Does not generate Python or pandas code.
- Does not include real file system paths.

Suggested heuristics:

Single-file vague examples:

- `clean this`
- `fix data`
- `process file`
- `make it better`

Single-file details to detect:

- Desired operation.
- Target column.
- Filter condition.
- Sort direction.
- Missing-value handling.
- Date format.
- Deduplication key.

Two-file vague examples:

- `merge these`
- `join files`
- `combine data`

Two-file details to detect:

- Logical file names.
- Join key.
- Join type.
- Which file should retain all rows.
- Desired output columns.
- Unmatched row behavior.

Acceptance criteria:

- Existing single-file behavior unaffected.
- Existing multi-file behavior unaffected.
- `clean this` returns `too_vague`.
- `Filter rows where amount is greater than 1000` returns `good`.
- `merge these files` returns `needs_detail` or `too_vague` with join key and join type missing.
- `Merge orders and products using pid with a left join and keep all orders` returns `good`.
- Advice never contains generated Python code.
- Advice never contains real file system paths.

Suggested verification:

```bash
uv run pytest tests/test_task_advisor.py
```

### Task 52: Streamlit Prompt Coach UI

**Goal:** Show non-blocking prompt advice in Streamlit.

**Likely files:**

- Modify: `src/snapscript/interfaces/web.py`
- Modify: `tests/test_streamlit_app.py`

Design notes:

- Runs rule-based advisor only.
- Does not call provider.
- Does not execute code.
- Does not block Generate.
- Shows status, missing details, suggestions, and optional suggested task.
- "Use suggested task" updates session `task_text` only.
- Uploading files or editing text must not call provider.
- Generate remains available even if advice quality is `needs_detail` or `too_vague`.
- Keep Streamlit thin: collect inputs, render advice, and call core helpers.

Acceptance criteria:

- Existing Streamlit tests pass.
- Prompt Coach appears after enough context exists.
- Prompt Coach works for single-file mode.
- Prompt Coach works for two-file mode.
- Prompt Coach missing details are shown clearly.
- Generate is not disabled by poor prompt quality.
- No provider call occurs when rendering Prompt Coach.
- No output preview/download state changes due to Prompt Coach.
- "Use suggested task" updates `task_text` only.

Suggested verification:

```bash
uv run pytest tests/test_streamlit_app.py
```

### Task 53: LLM Task Rewrite Core Helper

**Goal:** Add a core helper that rewrites user task descriptions through the configured provider boundary.

**Likely files:**

- Create: `src/snapscript/core/task_rewriter.py`
- Create: `src/snapscript/prompts/task_rewrite.txt`
- Create: `tests/test_task_rewriter.py`
- Optional modify: `src/snapscript/core/models.py`

Suggested dataclass:

```python
@dataclass(frozen=True)
class RewrittenTask:
    original_task: str
    rewritten_task: str
    provider: str
    model: str
```

Suggested API:

```python
def rewrite_task(
    original_task: str,
    schema: SchemaReport | MultiFileSchemaReport,
    advice: TaskAdvice | None = None,
    model: str | None = None,
) -> RewrittenTask:
    ...
```

Design notes:

- This is a core helper.
- Streamlit must call this helper instead of importing Anthropic or provider SDKs.
- The helper may reuse existing provider configuration.
- If needed, add a small provider-aware helper rather than duplicating provider logic in `web.py`.
- Do not call `code_generator.generate(...)` for task rewriting unless it is first refactored into a generic provider client. `code_generator` is for pandas code generation, while `task_rewriter` should produce natural-language task text only.
- The LLM rewrites only the natural-language task.
- The LLM must not generate Python code.
- The LLM must not mention real file paths.
- The LLM must not invent columns not present in the schema.
- The LLM should use logical file names for multi-file tasks.
- The LLM should make join key, join type, row retention, output columns, and missing-value behavior explicit when relevant.
- The helper should strip markdown/prose if the provider returns extra formatting.
- The helper should return a concise rewritten task string.

Prompt requirements for `src/snapscript/prompts/task_rewrite.txt`:

- You rewrite task descriptions for a CSV/Excel transformation tool.
- Do not generate Python code.
- Do not output markdown.
- Do not mention real file paths.
- Do not invent columns.
- Use only columns and logical file names shown in the schema.
- Return only the rewritten task text.

Acceptance criteria:

- Unit tests mock the provider boundary.
- Normal `uv run pytest` does not require `ANTHROPIC_API_KEY`.
- Rewriter does not call `retry_handler.run`.
- Rewriter does not call `safety_checker`.
- Rewriter does not call `execution_backend`.
- Rewriter does not create output files.
- Rewriter prompt includes schema summary but no real user paths.
- Returned rewritten task contains no markdown fence and no Python code.
- Provider errors are mapped to safe typed or user-facing errors.

Suggested verification:

```bash
uv run pytest tests/test_task_rewriter.py
env -u ANTHROPIC_API_KEY uv run pytest tests/test_task_rewriter.py
```

### Task 54: Streamlit AI Rewrite Button

**Goal:** Add an explicit "Improve task with AI" button that calls the core task rewriter.

**Likely files:**

- Modify: `src/snapscript/interfaces/web.py`
- Modify: `tests/test_streamlit_app.py`
- Modify: `tests/test_streamlit_pipeline_integration.py`

Design notes:

- The button must be explicit.
- No provider call on page load.
- No provider call on upload.
- No provider call on task text edit.
- Button first inspects schema or uses existing schema context.
- Button calls `task_advisor.advise_task` and `task_rewriter.rewrite_task`.
- Streamlit must not import Anthropic or provider SDKs.
- UI should show the rewritten task for review.
- Prefer not to overwrite `task_text` automatically.
- Provide "Use rewritten task" to update `task_text`.
- Do not run Generate automatically after rewrite.
- Do not create output bytes or preview/download state after rewrite.

Acceptance criteria:

- Existing Generate flow still works.
- AI rewrite button calls core rewriter only after click.
- AI rewrite button does not call `retry_handler.run`.
- AI rewrite button does not call `execution_backend`.
- AI rewrite button does not run sandbox.
- AI rewrite button does not create output file.
- User can accept rewritten task into `task_text`.
- User can ignore rewritten task and keep original task.
- Missing provider credentials show a safe concise error.
- Raw provider traceback is not shown.

Suggested verification:

```bash
uv run pytest tests/test_streamlit_app.py tests/test_streamlit_pipeline_integration.py
```

### Task 55: Rewrite Rate Limit, Audit, and Error Rules

**Goal:** Define and implement safe operational rules for AI rewrite calls.

**Likely files:**

- Modify: `src/snapscript/interfaces/web.py`
- Modify: `tests/test_streamlit_app.py`
- Optional modify: `src/snapscript/core/audit_logger.py`
- Optional create: `tests/test_task_rewrite_audit.py`

Design notes:

Rewrite is provider-backed but not a Generate run. Do not count task rewrites against Generate `run_count`.

Add separate rewrite limits, for example:

- Maximum 10 task rewrites per session.
- 3 second cooldown between accepted rewrite calls.

Session state suggestions:

- `rewrite_count: int`
- `last_rewrite_timestamp: float | None`
- `rewritten_task_suggestion: str | None`
- `rewrite_error_message: str | None`

Error rules:

- Missing provider key should show a concise setup message.
- Provider timeout or rate limit should show a concise retry/manual-edit message.
- No full tracebacks by default.
- No API keys or secret-like values in UI.
- Cap long error messages.

Audit rules:

If audit logging is extended to rewrites, record metadata only:

- `event_type = "task_rewrite"`
- `interface = "streamlit"`
- Provider.
- Model.
- Success/failure.
- `duration_ms`.
- `original_task_hash`.
- `rewritten_task_hash` if successful.
- `schema_summary_hash`.
- Whether provider call happened.
- Safe error category if failed.

Do not log:

- Raw uploaded CSV/Excel contents.
- Full raw prompts by default.
- API keys.
- `.env` contents.
- Environment variables.
- Secrets.
- Full tracebacks.
- Generated transformation code.

Acceptance criteria:

- Generate `run_count` and rewrite `rewrite_count` are separate.
- Rewrite cooldown blocks provider call.
- Rewrite limit blocks provider call.
- Blocked rewrite attempts do not increment `rewrite_count`.
- Accepted rewrite attempts increment `rewrite_count` before provider call.
- Safe errors are shown for provider failures.
- Optional audit events are metadata-only.
- Audit failure does not break rewrite UX.

Suggested verification:

```bash
uv run pytest tests/test_streamlit_app.py
uv run pytest tests/test_audit_logger.py  # only if audit_logger is modified
env -u ANTHROPIC_API_KEY uv run pytest
```

### Task 56: Prompt Assistant Tests

**Goal:** Add coverage for rule-based advice, rewrite helper, Streamlit UI orchestration, and no-provider default behavior.

**Likely files:**

- Create/modify: `tests/test_task_advisor.py`
- Create/modify: `tests/test_task_rewriter.py`
- Modify: `tests/test_streamlit_app.py`
- Modify: `tests/test_streamlit_pipeline_integration.py`
- Optional create: `tests/integration/test_task_rewriter_real_provider.py`

Required test themes:

- Rule-based advice for vague single-file tasks.
- Rule-based advice for good single-file tasks.
- Rule-based advice for vague two-file merge tasks.
- Rule-based advice for good two-file join tasks.
- Suggested task does not include Python code.
- Suggested task does not include real paths.
- Rewriter prompt does not include real paths.
- Rewriter does not call execution pipeline.
- Streamlit Prompt Coach does not block Generate.
- Streamlit Prompt Coach does not call provider.
- AI Rewrite button calls provider only after explicit click.
- AI Rewrite button does not create output preview/download.
- Rewrite rate limits are separate from Generate rate limits.
- Normal `uv run pytest` does not require provider credentials.
- Optional real-provider rewrite test is gated by `SNAPSCRIPT_REAL_PROVIDER=1`.

Suggested verification:

```bash
uv run pytest tests/test_task_advisor.py
uv run pytest tests/test_task_rewriter.py
uv run pytest tests/test_streamlit_app.py tests/test_streamlit_pipeline_integration.py
env -u ANTHROPIC_API_KEY uv run pytest
```

### Task 57: Phase 4B Gate

**Goal:** Confirm Prompt Assistant is complete without breaking Phase 4A behavior.

Required commands:

```bash
uv run pytest
env -u ANTHROPIC_API_KEY uv run pytest
uv run python main.py --help
uv run pytest tests/test_task_advisor.py
uv run pytest tests/test_task_rewriter.py
uv run pytest tests/test_streamlit_app.py tests/test_streamlit_pipeline_integration.py
uv run pytest tests/test_prompt_builder.py tests/test_retry_handler.py
uv run pytest tests/integration/test_multi_file_join.py
```

Optional real-provider rewrite gate:

```bash
SNAPSCRIPT_REAL_PROVIDER=1 uv run pytest tests/integration/test_task_rewriter_real_provider.py
```

Optional Docker regression gate:

```bash
docker build -t snapscript-sandbox:local docker/sandbox
SNAPSCRIPT_SANDBOX_BACKEND=docker uv run pytest tests/test_docker_sandbox_executor.py tests/test_execution_backend.py tests/test_retry_handler.py tests/integration/test_multi_file_join.py
```

Gate criteria:

- Full test suite passes.
- No-provider pytest passes.
- Normal pytest does not call a real provider.
- Normal pytest does not require Docker.
- Existing single-file CLI behavior still works.
- Existing single-file Streamlit behavior still works.
- Existing two-file CLI and Streamlit behavior still works.
- Prompt Coach warnings do not block Generate.
- Prompt Coach does not call provider.
- AI Rewrite calls provider only after explicit click.
- AI Rewrite does not generate pandas code.
- AI Rewrite does not execute sandbox.
- AI Rewrite does not create output files.
- Streamlit does not directly import Anthropic/provider SDK.
- Core remains UI-free.
- Generate still goes through the existing safe pipeline.
- Audit/logging remains metadata-only by default.
- No Phase 4B non-goals were added.

## 9. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Prompt Coach becomes a brittle parser. | Keep it as heuristic guidance only; do not convert natural language into operations. |
| Rewrite is mistaken for Generate. | Separate buttons and state; rewrite never creates code or output. |
| Streamlit calls provider directly. | Provider calls only through the core `task_rewriter` helper. |
| Provider cost grows. | Add a separate rewrite limit and cooldown. |
| Secrets or prompts leak into logs. | Use metadata-only audit and redacted errors. |
| Existing pipeline regresses. | Keep Phase 4A integration tests in the gate. |
| Prompt Coach blocks valid short tasks. | Advice is non-blocking. |

## 10. What Not To Do

- Do not block Generate based on prompt quality.
- Do not execute generated code from Prompt Coach or Rewrite.
- Do not generate pandas code in `task_rewriter`.
- Do not call `retry_handler.run` from `task_rewriter`.
- Do not call `execution_backend` from `task_rewriter`.
- Do not call provider SDK directly from Streamlit.
- Do not call provider on page load, upload, or text edit.
- Do not add a custom join parser.
- Do not implement merge logic in Streamlit or CLI.
- Do not weaken `safety_checker` or sandbox behavior.
- Do not log raw data, full prompts, generated code, API keys, or secrets.
- Do not make real-provider tests part of normal pytest.
- Do not make Docker required for normal pytest.

## 11. Final Note

Phase 4B is accepted when users get helpful task-quality guidance and optional AI task rewriting, while the actual transformation still flows through the existing SnapScript safe execution pipeline.
