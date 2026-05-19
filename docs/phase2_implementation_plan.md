# Phase 2 Streamlit Productization Implementation Plan

> **For agentic workers:** Recommended skills: `writing-plans`, `verification-before-completion`, `code-review`, `security-review`, and `webapp-testing` when implementing Streamlit UI tasks.

**Goal:** Build a thin Streamlit UI on top of the verified Phase 1 SnapScript CSV/Excel pipeline.

**Architecture:** Phase 2 adds a web interface only. `src/snapscript/core/` stays UI-free and keeps owning schema inspection, prompt construction, provider calls, AST safety checks, sandbox execution, output validation, and retry decisions. The Streamlit layer stores session UI state, handles uploaded files, enforces per-session rate limits, and calls the existing core pipeline after an explicit user click.

**Tech Stack:** Python 3.10+, uv, Streamlit, pandas, existing SnapScript core modules, existing pytest suite.

---

## 1. Phase 2 Goals

- Provide a usable local Streamlit UI for one-shot CSV/Excel transformations.
- Support drag/drop CSV and Excel upload.
- Capture a natural-language transformation task.
- Run generation and execution only when the user clicks Generate.
- Preview successful output and provide a download button.
- Show useful, redacted errors for failed runs.
- Preserve session state for uploaded file, task text, generated result, output bytes or path, error state, run count, and last run timestamp.
- Enforce max 10 runs per Streamlit session and a 5 second cooldown between runs.
- Keep Phase 1 CLI behavior and tests intact.

## 2. Non-goals

Phase 2 does not include:

- Multi-user accounts or login/auth.
- Database storage.
- Cloud backend or hosted execution service.
- Job queue.
- Team workspace.
- Billing.
- Persistent project history.
- Dashboard or observability product UI.
- MCP server.
- Production deployment.
- Docker sandbox replacement.
- Multi-file workflows.
- Data visualization or chart generation.

## 3. Architecture Boundary

The Streamlit UI must be thin:

- `src/snapscript/core/` must not import Streamlit or any web/UI framework.
- CLI/UI-only dependencies such as `argparse`, `click`, `rich`, or `sys.argv` must stay outside `core/`.
- Streamlit code should live in `src/snapscript/interfaces/web.py`.
- A small repo-root `app.py` may be added only as a Streamlit entrypoint that imports and calls `snapscript.interfaces.web.main()`.
- UI code may call existing core modules: `schema_inspector`, `prompt_builder`, and `retry_handler`.
- UI code must not directly call provider SDKs when existing core functions can be reused.
- UI code must not bypass `prompt_builder`, `code_generator`, `safety_checker`, `sandbox_executor`, or `retry_handler`.
- Generated code may run only through `retry_handler.run(...)`, which calls `safety_checker.check(...)` before `sandbox_executor.execute(...)`.

## 4. Proposed File Structure

- Create: `src/snapscript/interfaces/web.py`
  - Streamlit page layout, session state, upload handling, rate limiting, UI error rendering, output preview/download.
- Create: `app.py`
  - Minimal Streamlit entrypoint:
    ```python
    from snapscript.interfaces.web import main

    if __name__ == "__main__":
        main()
    ```
- Modify: `pyproject.toml`
  - Add `streamlit` only when implementing Task 21.
- Create: `tests/test_streamlit_app.py`
  - Unit tests for pure helper functions in `interfaces/web.py`.
- Optional create: `tests/test_streamlit_pipeline_integration.py`
  - Mock provider generation and exercise the web helper pipeline without launching a browser.

Do not create files under `src/snapscript/core/` unless a small interface-agnostic helper becomes necessary and is reviewed as core-safe.

## 5. Session State Design

Use stable keys in `st.session_state`:

| Key | Type | Purpose |
|-----|------|---------|
| `uploaded_file_name` | `str | None` | Original upload display name. |
| `uploaded_file_bytes` | `bytes | None` | Uploaded file bytes retained for reruns. |
| `uploaded_file_suffix` | `str | None` | `.csv`, `.xlsx`, or `.xls`. |
| `task_text` | `str` | Natural-language transformation task. |
| `result_preview` | `pandas.DataFrame | None` | First rows of validated output. |
| `output_bytes` | `bytes | None` | Downloadable output after sandbox validation. |
| `output_file_name` | `str | None` | Suggested download filename. |
| `error_message` | `str | None` | Redacted user-facing error. |
| `run_count` | `int` | Number of Generate attempts this session. |
| `last_run_timestamp` | `float | None` | `time.monotonic()` value of last accepted run. |
| `is_running` | `bool` | Prevent duplicate concurrent Generate handling in one rerun. |

For Phase 2 MVP, storing uploaded bytes in `st.session_state` is acceptable for local use. Keep this bounded with a 10 MB upload limit, and never log uploaded bytes, API keys, full prompts, generated code, or full file contents.

## 6. Rate Limiting Design

- Limit: 10 accepted Generate clicks per Streamlit session.
- Cooldown: 5 seconds between accepted Generate clicks.
- Show remaining runs as `10 - run_count`.
- Check cooldown before calling the provider.
- Increment `run_count` only after passing upload/task validation and accepting the run.
- If the user clicks too quickly, show a cooldown error and do not call any core generation path.
- If the user reaches 10 runs, disable Generate and show a clear session-limit message.

Suggested pure helper:

```python
def check_rate_limit(
    run_count: int,
    last_run_timestamp: float | None,
    now: float,
    max_runs: int = 10,
    cooldown_seconds: int = 5,
) -> tuple[bool, str | None]:
    if run_count >= max_runs:
        return False, "Run limit reached for this session."
    if last_run_timestamp is not None:
        remaining = cooldown_seconds - (now - last_run_timestamp)
        if remaining > 0:
            return False, f"Please wait {remaining:.1f}s before running again."
    return True, None
```

## 7. Streamlit UX Flow

1. Render a single-page app with upload, task text, Generate, output preview, download, and error area.
2. User uploads `.csv`, `.xlsx`, or `.xls`.
3. UI stores upload bytes and filename in session state.
4. User enters a natural-language task.
5. User clicks Generate.
6. UI validates upload type, 10 MB upload size limit, task text, run limit, and cooldown.
7. UI writes upload bytes to a temp input path with the original safe suffix.
8. UI chooses a temp output path with matching output suffix.
9. UI calls the existing core flow:
   ```python
   schema = schema_inspector.inspect(input_path)
   prompt = prompt_builder.build(task_text, schema)
   result = retry_handler.run(prompt, input_path, output_path)
   ```
10. On success, UI reads the validated output file, stores output bytes, previews rows with pandas, and shows download.
11. On failure, UI shows a redacted error and leaves previous successful output intact unless a new accepted run starts.

## 8. Error Handling Design

- Show concise user-facing errors for missing upload, empty task text, unsupported file type, rate limit, provider failure, safety violation, execution failure, and unreadable output.
- Do not display API keys, full prompts, generated code, `.env` values, or full stack traces by default.
- Redact any user-entered API key if Phase 2 adds a sidebar key field.
- Keep detailed traceback display out of Phase 2 MVP.
- Safety violations should be shown as transformation rejected, with short violation text.
- Sandbox failures should show stderr summary, capped to a small length such as 2,000 characters.

## API Key Handling

- Phase 2 MVP reads provider credentials from environment variables only.
- Do not add a UI text input for API keys in the MVP unless explicitly approved.
- Never store API keys in `st.session_state`.
- Never display API keys in errors.
- Never log API keys or secret-like values.
- Missing provider credentials should show a concise setup message.
- Normal `uv run pytest` must not require provider credentials.
- Real-provider checks remain explicit opt-in.

## 9. Security And Safety Rules

- Generated code must never run directly from Streamlit callbacks.
- All execution must go through `retry_handler.run(...)`.
- `retry_handler.run(...)` must still call `safety_checker.check(...)` before `sandbox_executor.execute(...)`.
- Uploaded files must be written only into temporary directories created for the run.
- Reject uploads larger than 10 MB before any provider call; this conservative local-MVP limit can be raised later after performance testing.
- Preserve original input bytes; do not overwrite the uploaded input.
- Download should use only the output file produced and validated by `sandbox_executor`.
- Do not log uploaded file contents, full prompts, generated code, API keys, or secrets.
- Do not make provider calls on page load, upload, text change, or preview rendering.
- Do not weaken allowed imports, blocked calls, path injection, output validation, or retry caps.
- Keep real-provider tests opt-in; normal `uv run pytest` must not call a real provider.

## 10. Testing Strategy

- Keep all Phase 1 tests passing.
- Unit-test pure Streamlit helper functions without launching a browser:
  - session state initialization defaults.
  - upload suffix validation.
  - 10 MB upload size rejection.
  - output filename derivation.
  - rate limit accepted/blocked cases.
  - error redaction and truncation.
- Integration-test the UI orchestration helper with mocked generation:
  - write upload bytes to temp input.
  - call schema inspection, prompt build, safety check, and sandbox execution through existing core flow.
  - produce output bytes only after `ExecutionResult.success`.
- Manual-check the Streamlit page:
  - upload fixture CSV.
  - enter one of the 10 gate prompts.
  - click Generate.
  - preview output.
  - download output.
  - verify cooldown and 10-run limit behavior.

## 11. Implementation Tasks

**Tracking status (updated 2026-05-19):** Tasks 21 through 31 are complete. Task 31 is a post-MVP follow-up and is not required for initial MVP completion.

| Task | Status |
|------|--------|
| Task 21: Streamlit Skeleton With Core Boundary | Complete |
| Task 22: File Upload And Temporary Input Handling | Complete |
| Task 23: Task Text Input And Generate Button | Complete |
| Task 24: Call Existing CLI/Core Pipeline From UI | Complete |
| Task 25: Output Preview And Download | Complete |
| Task 26: Session State Management | Complete |
| Task 27: Session Rate Limiting | Complete |
| Task 28: Error Display And Recovery UX | Complete |
| Task 29: Streamlit Tests / Manual Verification Checklist | Complete |
| Task 30: Gate - Phase 2 MVP Complete | Complete |
| Task 31: LLM Call Audit Logging | Complete |

Task 30 gate results on 2026-05-19:

- `uv run pytest`: passed, 212 tests.
- `env -u ANTHROPIC_API_KEY uv run pytest`: passed, 212 tests.
- `uv run python main.py --help`: passed.
- `SNAPSCRIPT_REAL_PROVIDER=1 uv run pytest tests/integration/test_cli_gate_tasks.py`: passed, 10/10.
- `uv run streamlit run app.py`: launched locally.
- Manual Streamlit gate flow passed with the Task 02 fixture through upload, Generate, preview, download availability, and cooldown behavior.
- `src/snapscript/core/` remained UI-free.
- Streamlit continued to call the existing safe path through `retry_handler.run(...)`.

### Task 21: Streamlit Skeleton With Core Boundary

**Goal:** Add the minimum Streamlit entrypoint and page shell without running provider calls.

**Files likely touched:**
- Create: `src/snapscript/interfaces/web.py`
- Create: `app.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock` if `uv sync` updates it
- Create: `tests/test_streamlit_app.py`

**Dependencies:** Task 20 complete.

**Acceptance criteria:**
- `streamlit` dependency is added only for Phase 2.
- `src/snapscript/core/` has no Streamlit import.
- Add or preserve an automated check proving `src/snapscript/core/` has no Streamlit/UI dependency.
- Existing Phase 1 boundary tests may be reused or strengthened.
- `app.py` only delegates to `snapscript.interfaces.web.main()`.
- Page renders title, file upload, task text area, Generate button placeholder, remaining runs, output area, and error area.
- Generate button does not call provider or execute code yet.

**Suggested verification command or manual check:**
```bash
uv sync
uv run pytest
uv run python -c "import pathlib; assert 'streamlit' not in ''.join(p.read_text() for p in pathlib.Path('src/snapscript/core').glob('*.py'))"
uv run streamlit run app.py
```

### Task 22: File Upload And Temporary Input Handling

**Goal:** Accept CSV/Excel uploads and write them safely to per-run temp files.

**Files likely touched:**
- Modify: `src/snapscript/interfaces/web.py`
- Modify: `tests/test_streamlit_app.py`

**Dependencies:** Task 21.

**Acceptance criteria:**
- Accept only `.csv`, `.xlsx`, `.xls`.
- Store upload name, suffix, and bytes in session state.
- Reject unsupported suffixes before any provider call.
- Reject uploads larger than 10 MB before any provider call.
- Write uploaded bytes into a `TemporaryDirectory` during a run.
- Use a sanitized internal temp filename; do not trust upload name as a path.
- Do not persist uploaded files outside temp storage.

**Suggested verification command or manual check:**
```bash
uv run pytest tests/test_streamlit_app.py
uv run streamlit run app.py
```

Manual check: upload `tests/fixtures/integration/task_02_orders.csv` and confirm the UI accepts it; upload a `.txt` file and confirm the UI rejects it.

### Task 23: Task Text Input And Generate Button

**Goal:** Capture natural-language task text and make Generate the only execution trigger.

**Files likely touched:**
- Modify: `src/snapscript/interfaces/web.py`
- Modify: `tests/test_streamlit_app.py`

**Dependencies:** Task 22.

**Acceptance criteria:**
- Task text is stored in `st.session_state["task_text"]`.
- Generate is disabled or blocked when upload is missing.
- Generate is disabled or blocked when task text is blank.
- Uploading a file or editing text does not call provider or execute generated code.
- Generate click starts validation and run flow.

**Suggested verification command or manual check:**
```bash
uv run pytest tests/test_streamlit_app.py
```

Manual check: refresh page, upload a file, type a task, and confirm no run starts until Generate is clicked.

### Task 24: Call Existing CLI/Core Pipeline From UI

**Goal:** Wire Generate to the existing safe core flow without duplicating pipeline logic in Streamlit.

**Files likely touched:**
- Modify: `src/snapscript/interfaces/web.py`
- Create or modify: `tests/test_streamlit_pipeline_integration.py`

**Dependencies:** Tasks 22 and 23.

**Acceptance criteria:**
- Generate writes upload bytes to temp input.
- Generate calls:
  ```python
  schema = schema_inspector.inspect(input_path)
  prompt = prompt_builder.build(task_text, schema)
  result = retry_handler.run(prompt, input_path, output_path)
  ```
- Use the actual existing Phase 1 function names and signatures from the repo; the snippet is conceptual and should not force API renaming.
- UI does not call Anthropic or any provider SDK directly.
- UI does not call `sandbox_executor.execute(...)` directly unless a reviewed interface-agnostic helper requires it; prefer `retry_handler.run(...)`.
- Safety checker and sandbox executor remain mandatory through `retry_handler`.
- Provider call happens only after explicit Generate click.

**Suggested verification command or manual check:**
```bash
uv run pytest tests/test_streamlit_pipeline_integration.py tests/test_pipeline_cli_integration.py
```

Manual check: run the app with `ANTHROPIC_API_KEY` set, upload `task_02_orders.csv`, enter "Keep only orders where amount is greater than 1000.", click Generate, and confirm an output is produced.

### Task 25: Output Preview And Download

**Goal:** Show a small output preview and provide a validated download.

**Files likely touched:**
- Modify: `src/snapscript/interfaces/web.py`
- Modify: `tests/test_streamlit_app.py`

**Dependencies:** Task 24.

**Acceptance criteria:**
- Preview reads only from the validated output path after `ExecutionResult.success`.
- Preview uses a bounded row count such as `nrows=100`.
- Download bytes come from the validated output file copied by `sandbox_executor`.
- Download button is hidden or disabled before a successful run.
- Download filename is derived from upload stem plus `_snapscript_output` and a safe suffix.
- Failed runs do not expose a new download.

**Suggested verification command or manual check:**
```bash
uv run pytest tests/test_streamlit_app.py tests/test_streamlit_pipeline_integration.py
```

Manual check: after a successful run, confirm preview rows render and the downloaded CSV opens with expected transformed rows.

### Task 26: Session State Management

**Goal:** Make reruns predictable by centralizing Streamlit session defaults and state transitions.

**Files likely touched:**
- Modify: `src/snapscript/interfaces/web.py`
- Modify: `tests/test_streamlit_app.py`

**Dependencies:** Tasks 21-25.

**Acceptance criteria:**
- A single helper initializes all required session keys.
- New accepted run clears previous error and stale output state before execution.
- Failed run stores `error_message` and does not store output bytes for that run.
- Successful run stores preview, output bytes, output filename, and clears error.
- State keys match the table in Section 5.

**Suggested verification command or manual check:**
```bash
uv run pytest tests/test_streamlit_app.py
```

Manual check: run once successfully, then trigger a validation error, and confirm the error appears without corrupting the session.

### Task 27: Session Rate Limiting

**Goal:** Enforce 10 runs per session and 5 second cooldown before provider calls.

**Files likely touched:**
- Modify: `src/snapscript/interfaces/web.py`
- Modify: `tests/test_streamlit_app.py`

**Dependencies:** Task 26.

**Acceptance criteria:**
- Show remaining runs.
- Block run when `run_count >= 10`.
- Block run when last accepted run was less than 5 seconds ago.
- Blocked cooldown and limit attempts do not call provider or increment `run_count`.
- Accepted Generate click increments `run_count` before provider execution starts.

**Suggested verification command or manual check:**
```bash
uv run pytest tests/test_streamlit_app.py
```

Manual check: click Generate twice quickly and confirm the second click shows cooldown. After 10 accepted runs, confirm Generate is blocked.

### Task 28: Error Display And Recovery UX

**Goal:** Surface useful errors without leaking secrets or internal details.

**Files likely touched:**
- Modify: `src/snapscript/interfaces/web.py`
- Modify: `tests/test_streamlit_app.py`

**Dependencies:** Tasks 24-27.

**Acceptance criteria:**
- Missing upload, blank task, unsupported suffix, cooldown, run limit, provider failure, safety violation, and sandbox failure have distinct user-facing messages.
- Error text is capped to a small length.
- API keys and common secret-like values are redacted.
- Full tracebacks are not shown by default.
- User can change task or upload a new file and run again if limits allow.

**Suggested verification command or manual check:**
```bash
uv run pytest tests/test_streamlit_app.py tests/test_streamlit_pipeline_integration.py
```

Manual check: run without `ANTHROPIC_API_KEY` and confirm the app shows a concise provider/config error without exposing secrets.

### Task 29: Streamlit Tests / Manual Verification Checklist

**Goal:** Add enough automated and manual coverage to protect Phase 2 behavior without making normal pytest call the provider.

**Files likely touched:**
- Modify: `tests/test_streamlit_app.py`
- Modify: `tests/test_streamlit_pipeline_integration.py`
- Optional create: `docs/phase2_manual_verification.md`

**Dependencies:** Tasks 21-28.

**Acceptance criteria:**
- `uv run pytest` passes without `ANTHROPIC_API_KEY`.
- Streamlit helper tests cover state, upload validation, rate limiting, error redaction, output filename, and download gating.
- Integration test mocks `code_generator.generate(...)` or equivalent provider boundary.
- Manual checklist covers upload, Generate, preview, download, cooldown, run limit, provider missing key, and safety failure.
- Real-provider Streamlit check remains manual or explicit opt-in.

**Suggested verification command or manual check:**
```bash
env -u ANTHROPIC_API_KEY uv run pytest
uv run pytest tests/test_streamlit_app.py tests/test_streamlit_pipeline_integration.py
```

Manual check: run `uv run streamlit run app.py` and complete the checklist with one fixture task.

### Task 30: Gate - Phase 2 MVP Complete

**Goal:** Decide whether the Streamlit MVP is complete enough for user observation.

**Files likely touched:**
- Modify: `docs/phase2_implementation_plan.md` only to mark completed tasks, if this doc is being used for tracking.
- Optional modify: `docs/phase2_manual_verification.md`

**Dependencies:** Tasks 21-29.

**Acceptance criteria:**
- Full test suite passes.
- Normal pytest does not call a real provider.
- CLI still works.
- Real-provider CLI gate still passes at least 8/10 first-attempt.
- The real-provider CLI gate is required for Task 30 or major prompt/core changes; normal Phase 2 UI development should rely on mocked tests unless explicitly running that gate.
- Streamlit app launches locally.
- Upload, task entry, Generate, preview, download, errors, session state, and rate limiting work manually.
- `src/snapscript/core/` remains UI-free.
- Safety checker and sandbox executor remain mandatory in execution path.
- No Phase 2 non-goals were added.

**Suggested verification command or manual check:**
```bash
uv run pytest
env -u ANTHROPIC_API_KEY uv run pytest
uv run python main.py --help
SNAPSCRIPT_REAL_PROVIDER=1 uv run pytest tests/integration/test_cli_gate_tasks.py
uv run streamlit run app.py
```

Manual gate checklist:

- Upload `tests/fixtures/integration/task_02_orders.csv`.
- Enter "Keep only orders where amount is greater than 1000."
- Click Generate once.
- Confirm preview only shows rows with `amount > 1000`.
- Download output and open it.
- Click Generate again immediately and confirm cooldown error.
- Confirm remaining runs decreases only for accepted runs.

### Task 31: LLM Call Audit Logging

**Goal:** Record safe local metadata for each accepted Generate run so developers can confirm provider usage and debug failures without storing secrets or raw user data.

**Post-MVP note:** This task is after the Phase 2 MVP gate and is not required for initial MVP completion.

**Recommended approach:**
- Start with append-only JSONL audit logs, not MLflow.
- Proposed local path: `logs/snapscript_audit.jsonl`, or another local `logs/` path.
- Ensure `logs/` is gitignored if it is not already.
- Prefer an interface-agnostic helper such as `src/snapscript/core/audit_logger.py` if it does not introduce UI dependencies.
- Streamlit may call the helper, but core must not import Streamlit.
- Audit logging must not bypass `retry_handler.run(...)`.
- Audit logging must not change execution behavior.
- Audit logging failure should not fail the user's transformation by default; it should be best-effort unless explicitly configured otherwise.
- MLflow may be reconsidered later only if experiment tracking becomes necessary.

**Files likely touched:**
- Create: `src/snapscript/core/audit_logger.py` or another interface-agnostic helper.
- Modify: `src/snapscript/interfaces/web.py`.
- Modify/Create: `tests/test_audit_logger.py`.
- Modify: `tests/test_streamlit_app.py` or `tests/test_streamlit_pipeline_integration.py`.
- Modify: `.gitignore` if `logs/` is not already ignored.

**Dependencies:** Task 30.

**Default audit event metadata:**
- `timestamp`
- `run_id`
- `interface = "streamlit"`
- `provider`
- `model`
- `success` or `failure`
- `duration_ms`
- input filename, file size, and SHA-256 hash
- task text SHA-256 hash
- schema summary SHA-256 hash
- prompt SHA-256 hash
- generated code SHA-256 hash, if available from the existing pipeline
- output filename, file size, and SHA-256 hash
- error category, if failed
- retry count or attempt count, if available
- whether a provider call happened

**Privacy and security rules:**
- Never log API keys, environment variables, `.env` contents, secrets, full uploaded CSV contents, full raw dataset rows, or full tracebacks by default.
- Store metadata and hashes by default, not raw sensitive content.
- Redact API-key-like and secret-like values before writing audit records.
- Optional local debug mode may use an explicit opt-in env var such as `SNAPSCRIPT_AUDIT_INCLUDE_PROMPTS=1`.
- Only explicit debug mode may include full task text, full system/user prompt, or generated code.
- Even in debug mode, never log API keys or full uploaded CSV contents, and still redact secrets.
- Logs must remain local and gitignored.

**Acceptance criteria:**
- Accepted Streamlit Generate runs write one audit event.
- Audit event records provider/model, timestamp, run ID, interface, duration, success/failure, and safe hashes.
- Audit event can indicate whether a provider call happened.
- Audit event records input/output metadata and SHA-256 hashes, not raw file contents.
- API keys and secret-like values are redacted.
- Full prompt, task text, and generated code are not logged by default.
- Optional debug env var can include prompt/task/code for local-only debugging.
- Full uploaded CSV contents are never logged by default.
- Failed provider, safety, and sandbox runs record a safe error category.
- Audit logging failure does not break successful transformations.
- Normal pytest still does not call a real provider.

**Suggested verification commands:**
```bash
uv run pytest tests/test_audit_logger.py tests/test_streamlit_app.py tests/test_streamlit_pipeline_integration.py
env -u ANTHROPIC_API_KEY uv run pytest
uv run pytest
```

**Non-goals:**
- Do not add MLflow yet.
- Do not add a database.
- Do not add cloud logging.
- Do not add user accounts or persistent multi-user history.
- Do not log raw uploaded datasets.
- Do not log secrets.
- Do not make audit logging a replacement for `safety_checker` or `sandbox_executor`.

## 12. Acceptance Criteria

Phase 2 MVP is accepted when:

- `uv run pytest` passes.
- `env -u ANTHROPIC_API_KEY uv run pytest` passes.
- `uv run python main.py --help` works.
- `SNAPSCRIPT_REAL_PROVIDER=1 uv run pytest tests/integration/test_cli_gate_tasks.py` passes at least 8/10 first-attempt.
- `uv run streamlit run app.py` launches the UI.
- Core remains interface-agnostic.
- Streamlit code lives under `src/snapscript/interfaces/` plus a minimal root entrypoint.
- Generate is the only action that can call the provider.
- Rate limiting is enforced before provider calls.
- Output is downloadable only after sandbox validation.
- Failed runs show useful redacted errors.

## 13. Verification Commands

Core and tests:

```bash
uv run pytest
env -u ANTHROPIC_API_KEY uv run pytest
uv run python main.py --help
uv run pytest tests/test_streamlit_app.py tests/test_streamlit_pipeline_integration.py
```

Real-provider CLI gate:

```bash
SNAPSCRIPT_REAL_PROVIDER=1 uv run pytest tests/integration/test_cli_gate_tasks.py
```

Run this only for Task 30 or major prompt/core changes. Do not run real-provider checks automatically in normal `uv run pytest`; normal Phase 2 UI development should rely on mocked tests unless the real-provider gate is explicitly requested.

Local Streamlit app:

```bash
uv run streamlit run app.py
```

Core boundary check:

```bash
rg -n "streamlit|\\bst\\.|gradio|fastapi|flask|dash|rich|argparse|click|sys\\.argv" src/snapscript/core
```

Expected: no matches.

## 14. Risks And Mitigations

| Risk | Mitigation |
|------|------------|
| UI bypasses safety/sandbox path | Call `retry_handler.run(...)`; add tests that spy on safety and sandbox execution. |
| Provider calls happen on page load | Put provider path only inside Generate-click branch; test helper flow separately. |
| Uploaded file path traversal | Ignore upload name for paths; write bytes to a temp file with validated suffix. |
| Secrets leak in errors | Redact API keys and cap error output; do not show tracebacks by default. |
| Session reruns duplicate work | Use `is_running`, explicit button handling, and stable session state transitions. |
| Normal pytest spends API calls | Mock provider boundary in Streamlit tests; keep real-provider checks opt-in. |
| Core gains UI dependencies | Add boundary tests and run the `rg` check before Phase 2 gate. |
| UI becomes a dashboard | Keep one workflow: upload, describe task, generate, preview, download. |

## 15. What Not To Do

- Do not rewrite the core pipeline.
- Do not move business logic into Streamlit callbacks.
- Do not add auth, database, cloud backend, job queue, billing, or persistent history.
- Do not add Streamlit imports to `src/snapscript/core/`.
- Do not weaken `safety_checker`, `sandbox_executor`, path injection, output validation, or retry limits.
- Do not make real-provider calls automatic on page load.
- Do not run generated code outside the existing safe pipeline.
- Do not log uploaded file contents, full prompts, generated code, `.env`, API keys, or secrets.
- Do not make normal `uv run pytest` require `ANTHROPIC_API_KEY`.
- Do not start production deployment work in Phase 2 MVP.
