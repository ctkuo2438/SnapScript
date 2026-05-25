# Phase 4A Multi-file Input Support Implementation Plan

> Recommended workflow: implement tasks incrementally and verify each task before moving to the next. Phase 4A is limited to two-file CSV/Excel workflows and must preserve all single-file behavior from Phases 1 through 3.

**Goal:** Add named multi-file input support for two-file CSV/Excel workflows such as joins and merges while preserving the existing single-file CLI, Streamlit, safety, retry, and sandbox behavior.

**Architecture:** Phase 4A extends the existing safe core pipeline instead of adding merge logic to interfaces. CLI and Streamlit collect one or two input files, schema inspection describes named files, prompt building instructs generated code to use safe path variables, and execution still flows through `code_generator`, `safety_checker`, `execution_backend`, sandbox execution, output validation, and retry handling. Generated code must never receive real user paths; `_snapscript_paths.py` remains the only path injection mechanism and is extended to support `INPUT_PATHS`.

**Tech Stack:** Python 3.10+, uv, pandas, openpyxl, chardet, existing SnapScript core modules, existing subprocess and Docker sandbox backends, Streamlit, pytest, and the configured LLM provider SDK.

---

## 1. Phase 4A Goals

- Add multi-file input support as a core capability, with Phase 4A initially limited to at most two files.
- Support named logical input files such as `orders=orders.csv` and `products=products.csv`.
- Preserve single-file CLI compatibility with `--file input.csv`.
- Preserve single-file Streamlit compatibility with the existing upload workflow.
- Inspect schemas for multiple named CSV/Excel files without reading entire large files.
- Build prompts that contain named schema sections and instruct generated code to use `INPUT_PATHS`.
- Extend `_snapscript_paths.py` so generated code can import `INPUT_PATHS` and `OUTPUT_PATH` in multi-file mode.
- Preserve `INPUT_PATH` for single-file backward compatibility.
- Keep the existing high-level pipeline and retry behavior intact.
- Add mocked-provider integration tests proving inner and left joins work through real sandbox execution.

Target multi-file CLI design:

```bash
uv run python main.py \
  "Please merge orders and products using the pid column with an inner join." \
  --file orders=orders.csv \
  --file products=products.csv \
  --output output.csv \
  --yes
```

Single-file compatibility must remain:

```bash
uv run python main.py \
  "Keep only orders where amount is greater than 1000." \
  --file orders.csv \
  --output output.csv \
  --yes
```

## 2. Non-goals

Phase 4A does not include:

- Unlimited number of input files.
- More than two input files in the CLI or Streamlit UI.
- A general relational query planner.
- Custom SnapScript keyword parsing for natural-language join instructions.
- Database connectors.
- Cloud execution.
- Auth, billing, accounts, team workspaces, dashboards, or persistent project history.
- Data visualization.
- Multi-step pipeline chaining.
- Weakening the sandbox, safety checker, path injection, output validation, retry limits, Docker restrictions, or provider opt-in rules.
- Logging raw uploaded datasets, full prompts, generated code, API keys, `.env` contents, secrets, environment variables, or full tracebacks by default.
- Making Docker required for normal `uv run pytest`.
- Making provider credentials required for normal `uv run pytest`.

## 3. Current Project History

Phase 1 built the CLI/core pipeline for single-file CSV/Excel processing:

```text
schema inspection
  -> prompt building
  -> code generation
  -> safety checking
  -> sandbox execution
  -> output validation
  -> retry handling
```

Phase 2 added a thin Streamlit UI on top of the same safe core pipeline:

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

Phase 3 added Docker sandbox hardening and a backend router while preserving the same two-layer safety architecture:

```text
retry_handler.run(...)
  -> code_generator.generate(...)
  -> safety_checker.check(...)
  -> execution_backend.execute(...)
      -> sandbox_executor.execute(...)
      -> docker_sandbox_executor.execute(...)
```

Phase 4A must extend this architecture for named multi-file inputs without letting interfaces call provider SDKs or execute generated code directly.

## 4. Architecture Boundary

All Phase 4A work must preserve these rules:

- `src/snapscript/core/` must remain interface-agnostic.
- `src/snapscript/core/` must not import Streamlit, argparse, click, rich rendering, or direct UI state.
- CLI and Streamlit must stay thin interface layers.
- Interfaces may collect files, validate UI/CLI input shape, and call core entrypoints.
- Interfaces must not call provider SDKs directly.
- Interfaces must not execute generated code directly.
- Interfaces must not implement merge or join business logic.
- Generated code must still go through:

```text
prompt_builder
  -> code_generator
  -> safety_checker
  -> execution_backend
  -> sandbox execution
  -> output validation
```

- `safety_checker.check(...)` remains mandatory before any sandbox backend.
- Docker sandboxing does not replace AST safety checking.
- `execution_backend` still routes to subprocess or Docker by config.
- `_snapscript_paths.py` remains the path injection mechanism.
- Do not inject real user paths into prompts or generated code.
- Do not use naive string replacement for file paths.
- Normal `uv run pytest` must not require provider credentials.
- Normal `uv run pytest` must not require Docker.
- Real-provider tests must remain explicit opt-in with `SNAPSCRIPT_REAL_PROVIDER=1`.
- Docker-specific verification must remain explicit or be skipped unless Docker is available.

Target Phase 4A multi-file execution flow:

```text
CLI / Streamlit
  -> collect one or two input files
  -> validate logical names for multi-file mode
  -> schema_inspector.inspect(...) or inspect_many(...)
  -> prompt_builder.build(...) or build_many(...)
  -> retry_handler.run(...) or adjacent high-level helper
      -> code_generator.generate(...)
      -> safety_checker.check(...)
      -> execution_backend.execute(...)
          -> sandbox_executor.execute(...)
          -> docker_sandbox_executor.execute(...)
      -> output validation
```

## 5. Proposed File Structure

Core models and schema inspection:

- Modify: `src/snapscript/core/models.py`
  - Add `InputFileSpec`, `NamedSchemaReport`, and `MultiFileSchemaReport` or equivalent shared dataclasses.
- Modify: `src/snapscript/core/schema_inspector.py`
  - Preserve `inspect(path: Path, sheet: str | None = None) -> SchemaReport`.
  - Add `inspect_many(inputs: list[InputFileSpec]) -> MultiFileSchemaReport` or equivalent.
- Modify: `tests/test_models.py`
- Modify: `tests/test_schema_inspector.py`

Prompt building:

- Modify: `src/snapscript/core/prompt_builder.py`
  - Preserve existing single-file prompt behavior.
  - Add a multi-file prompt path or carefully extend the existing builder.
- Modify: `src/snapscript/prompts/system.txt` only if needed to document `INPUT_PATHS` for multi-file generated code.
- Modify: `tests/test_prompt_builder.py`

Path injection and sandbox backends:

- Modify: `src/snapscript/core/sandbox_executor.py`
  - Extend `_snapscript_paths.py` writing for `INPUT_PATHS`.
- Modify: `src/snapscript/core/docker_sandbox_executor.py`
  - Match subprocess multi-file workspace behavior.
- Modify or create a private shared helper only if it reduces duplicated workspace/path handling without coupling to interfaces.
- Modify: `tests/test_sandbox_executor.py`
- Modify: `tests/test_docker_sandbox_executor.py`

Pipeline and backend routing:

- Modify: `src/snapscript/core/retry_handler.py`
  - Preserve `run(prompt, input_path, output_path)` compatibility.
  - Add multi-file support through an adjacent helper or backward-compatible signature.
- Modify: `src/snapscript/core/execution_backend.py`
  - Preserve backend routing while accepting the multi-file input representation.
- Modify: `tests/test_retry_handler.py`
- Modify: `tests/test_execution_backend.py`

Interfaces:

- Modify: `src/snapscript/interfaces/cli.py`
  - Add repeated `--file` handling.
- Modify: `src/snapscript/interfaces/web.py`
  - Add simple two-file upload support.
- Modify: `tests/test_cli.py`
- Modify: `tests/test_streamlit_app.py`
- Modify: `tests/test_streamlit_pipeline_integration.py`

Integration tests:

- Create: `tests/integration/test_multi_file_join.py`
- Optional create: `tests/integration/test_multi_file_join_real_provider.py`

Do not create these files before their associated task. Each task should stay independently reviewable.

## 6. Multi-file Path Variables

Generated code for multi-file mode should import:

```python
from _snapscript_paths import INPUT_PATHS, OUTPUT_PATH
```

Example `_snapscript_paths.py` for multi-file mode:

```python
INPUT_PATH = None
INPUT_PATHS = {
    "orders": "orders.csv",
    "products": "products.csv",
}
OUTPUT_PATH = "output.csv"
```

Example `_snapscript_paths.py` for single-file backward compatibility:

```python
INPUT_PATH = "input.csv"
INPUT_PATHS = {
    "input": "input.csv"
}
OUTPUT_PATH = "output.csv"
```

The concrete values in `_snapscript_paths.py` must be safe workspace paths or safe workspace-relative names, never original user paths. Prompt content must mention only `INPUT_PATH`, `INPUT_PATHS`, and `OUTPUT_PATH`, not absolute source paths.

## 7. Phase 4A Task List

| Task | Status |
|------|--------|
| Task 43: Multi-file Core Models + Schema Inspection | Planned |
| Task 44: Multi-file Prompt Builder | Planned |
| Task 45: Multi-file Sandbox Path Injection | Planned |
| Task 46: Retry/Core Pipeline Accepts Input Files Collection | Planned |
| Task 47: CLI Two-file Support | Planned |
| Task 48: Streamlit Multi-upload Support | Planned |
| Task 49: Multi-file Join Integration Tests | Planned |
| Task 50: Phase 4A Gate | Planned |

## 8. Task-by-task Details

### Task 43: Multi-file Core Models + Schema Inspection

**Goal:** Add core data structures for named input files and schema inspection across multiple files.

**Files likely touched:**

- Modify: `src/snapscript/core/models.py`
- Modify: `src/snapscript/core/schema_inspector.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_schema_inspector.py`

**Dependencies:** Phase 3 complete.

**Design notes:**

- Add `InputFileSpec` or equivalent with fields such as:
  - `name: str`
  - `path: Path`
  - `sheet: str | None = None`
  - optional `display_filename: str | None = None`
- Add `NamedSchemaReport` or equivalent to pair a logical name with a `SchemaReport`.
- Add `MultiFileSchemaReport` or equivalent to hold an ordered collection of named schemas.
- Keep existing single-file `SchemaReport` unchanged unless new fields are added at the end with safe defaults.
- Preserve `inspect(path: Path, sheet: str | None = None) -> SchemaReport`.
- Add `inspect_many(inputs: list[InputFileSpec]) -> MultiFileSchemaReport` or equivalent.
- Validate logical names in core so CLI and Streamlit share the same rules.
- Recommended logical name shape: lowercase letters, numbers, and underscores, starting with a letter, for example `orders`, `products`, `customers_2025`.
- Trim whitespace from CLI/UI logical name input before validation.
- Do not silently change case.
- Reject names that are not already valid.
- Valid examples: `orders`, `products`, `customers_2025`.
- Invalid examples: `Orders`, `customer-id`, `customer id`, `1_orders`.
- Reject duplicate logical names.
- Reject unsupported suffixes through the same supported extension rules as single-file inspection.
- Preserve row/sample/schema limits from existing `schema_inspector`.
- Do not read entire large files.
- Keep CSV, `.xlsx`, and `.xls` support.
- Preserve current schema inspection error behavior and typed exceptions where possible.

**Acceptance criteria:**

- Existing single-file schema inspection tests still pass.
- `inspect(...)` remains callable by existing code.
- `inspect_many(...)` returns schemas for two named input files in stable input order.
- Duplicate logical names are rejected before prompt building.
- Invalid logical names are rejected before prompt building.
- Unsupported file types are rejected.
- Missing files are rejected.
- Large-file sampling limits are preserved.
- CSV and Excel-capable paths remain supported.

**Suggested tests:**

- Two CSV files produce a `MultiFileSchemaReport` with two named schema reports.
- Two Excel-capable paths work if fixtures or generated temporary workbooks exist.
- Duplicate names fail.
- Invalid names fail.
- Unsupported suffix fails.
- Missing file fails.
- Existing `inspect(path)` single-file behavior remains unchanged.

**Suggested verification command:**

```bash
uv run pytest tests/test_models.py tests/test_schema_inspector.py
```

### Task 44: Multi-file Prompt Builder

**Goal:** Build prompts that include multiple named schemas and instruct generated code to use `INPUT_PATHS`.

**Files likely touched:**

- Modify: `src/snapscript/core/prompt_builder.py`
- Modify: `src/snapscript/prompts/system.txt` only if needed for multi-file generated code instructions.
- Modify: `tests/test_prompt_builder.py`

**Dependencies:** Task 43.

**Design notes:**

- Keep existing single-file prompt builder behavior and tests passing.
- Add a multi-file prompt builder path such as `build_many(task_description, multi_schema)` or carefully extend `build(...)` without breaking callers.
- Multi-file prompts should use a `<schemas>` block.
- The `<schemas>` block should contain one `<file name="...">` section per logical input file.
- Include logical file names, original display filenames, file type, columns, dtypes, sample rows, row count metadata if available, encoding, and sheet names where relevant.
- User task remains outside the schema block.
- Prompt must mention `INPUT_PATHS` and `OUTPUT_PATH` only, not real paths.
- Prompt must instruct generated code to use `INPUT_PATHS["orders"]`, `INPUT_PATHS["products"]`, or whatever logical names were supplied.
- Prompt must instruct generated code not to hardcode paths.
- Prompt must instruct generated code to write final output to `OUTPUT_PATH`.
- Prompt must include join/merge guidance for the LLM:
  - inner join -> `how="inner"`
  - left join / keep all rows from first file -> `how="left"`
  - right join / keep all rows from second file -> `how="right"`
  - outer join / keep all rows from both files -> `how="outer"`
- This guidance is prompt text only. Do not implement keyword parsing in SnapScript business logic.
- Sample truncation should still protect prompt budget.

Example multi-file prompt shape:

```text
## Input files information
<schemas>
<file name="orders">
...
</file>
<file name="products">
...
</file>
</schemas>

## Task description
Please merge orders and products using the pid column with an inner join.

## Output requirement
Read input files by using INPUT_PATHS["orders"] and INPUT_PATHS["products"].
Write exactly one primary output file to OUTPUT_PATH.
```

**Acceptance criteria:**

- Existing single-file prompt builder tests still pass.
- Multi-file prompt includes a `<schemas>` block.
- Multi-file prompt includes one named file section per input.
- Multi-file prompt includes logical names and display filenames.
- Multi-file prompt does not contain real user paths.
- User task appears outside the schema block.
- Prompt mentions `INPUT_PATHS`.
- Prompt mentions `OUTPUT_PATH`.
- Prompt includes join/merge guidance for the LLM.
- Prompt sample truncation still works.

**Suggested tests:**

- Multi-file schema block renders both file names.
- Real absolute temp paths do not appear in `PromptPayload.user_prompt`.
- User task appears after `</schemas>`.
- `INPUT_PATHS["orders"]`, `INPUT_PATHS["products"]`, and `OUTPUT_PATH` are present.
- Very large sample data is truncated.
- Existing single-file prompt still uses `INPUT_PATH` and `OUTPUT_PATH`.

**Suggested verification command:**

```bash
uv run pytest tests/test_prompt_builder.py
```

### Task 45: Multi-file Sandbox Path Injection

**Goal:** Extend subprocess and Docker sandbox path injection to support multiple copied input files through `INPUT_PATHS`.

**Files likely touched:**

- Modify: `src/snapscript/core/sandbox_executor.py`
- Modify: `src/snapscript/core/docker_sandbox_executor.py`
- Modify: `src/snapscript/core/execution_backend.py` if the backend contract changes here.
- Optional modify/create: private shared workspace/path helper under `src/snapscript/core/`.
- Modify: `tests/test_sandbox_executor.py`
- Modify: `tests/test_docker_sandbox_executor.py`
- Modify: `tests/test_execution_backend.py` if needed.

**Dependencies:** Tasks 43 and 44.

**Design notes:**

- Preserve `_snapscript_paths.py` as the path injection mechanism.
- Do not replace `_snapscript_paths.py` with string substitution.
- Use the same `InputFileSpec` representation, or its approved equivalent, across schema inspection, prompt building, retry handling, execution backend, and sandbox executors.
- Avoid introducing separate ad-hoc dict/list shapes in CLI, Streamlit, or sandbox code. For example, do not let CLI use `{"orders": path}`, sandbox use `[("orders", path)]`, and schema inspection use `InputFileSpec(...)`.
- Copy every input file into the per-run temp workspace using sanitized safe filenames.
- Generated code must never receive original user paths.
- For single-file mode, preserve `INPUT_PATH` compatibility.
- For single-file mode, also provide `INPUT_PATHS = {"input": INPUT_PATH}` for forward-compatible generated code.
- For multi-file mode, write `INPUT_PATH = None` and `INPUT_PATHS = {...}`.
- Use logical names as dictionary keys.
- Use sanitized copied workspace filenames or workspace paths as dictionary values.
- Avoid path collisions when two inputs have the same display filename.
- Subprocess and Docker should share equivalent workspace layout behavior.
- Docker must still mount only the per-run temp workspace.
- Do not mount the repo root.
- Do not mount the user's home directory.
- Do not weaken Docker runtime restrictions such as network-disabled mode, memory limits, CPU limits, or PID limits.
- Output validation remains required before copying output out.
- Missing, empty, or unreadable output still fails.

**Acceptance criteria:**

- Existing single-file subprocess sandbox tests still pass.
- Existing Docker sandbox tests still pass or remain skipped when Docker is unavailable.
- `_snapscript_paths.py` contains `INPUT_PATH`, `INPUT_PATHS`, and `OUTPUT_PATH`.
- Multi-file `_snapscript_paths.py` does not contain original user paths.
- Input files are copied into the per-run temp workspace with safe names.
- Generated code can read both input files through `INPUT_PATHS`.
- Output is validated before copy-out.
- Docker command construction still mounts only the per-run workspace.
- Failure behavior remains consistent for missing output, empty output, unreadable output, non-zero exit, and timeout.

**Suggested tests:**

- Assert `_snapscript_paths.py` content for single-file mode.
- Assert `_snapscript_paths.py` content for multi-file mode.
- Assert copied workspace files use safe names.
- Assert original paths are absent from generated path module content.
- Subprocess execution succeeds with code that reads `INPUT_PATHS["orders"]` and `INPUT_PATHS["products"]`.
- Docker command construction includes only the workspace mount.
- Docker and subprocess failures still map to `ExecutionResult(success=False)`.

**Suggested verification command:**

```bash
uv run pytest tests/test_sandbox_executor.py tests/test_docker_sandbox_executor.py tests/test_execution_backend.py
```

### Task 46: Retry/Core Pipeline Accepts Input Files Collection

**Goal:** Allow the high-level safe execution path to accept either one input file or a collection of named input files.

**Files likely touched:**

- Modify: `src/snapscript/core/retry_handler.py`
- Modify: `src/snapscript/core/execution_backend.py`
- Modify: `tests/test_retry_handler.py`
- Modify: `tests/test_execution_backend.py`

**Dependencies:** Task 45.

**Design notes:**

- Preserve the existing `retry_handler.run(prompt, input_path, output_path)` call path for single-file callers.
- Add multi-file support through one of these approaches:
  - an adjacent helper such as `run_many(prompt, inputs, output_path)`, or
  - a backward-compatible `run(...)` signature that can accept a single `Path` or a typed collection.
- The typed collection should use the shared `InputFileSpec` representation, or its approved equivalent, all the way through prompt building, retry handling, backend routing, and sandbox execution.
- CLI and Streamlit should convert validated user input into that shared representation and then pass it into core; they should not keep their own ad-hoc shapes after validation.
- Keep the high-level flow unchanged:

```text
code_generator.generate(...)
  -> safety_checker.check(...)
  -> execution_backend.execute(...)
  -> output validation
  -> retry/fallback logic
```

- Avoid duplicating the pipeline in CLI or Streamlit.
- `execution_backend` should route to subprocess or Docker as before.
- Existing retry behavior and fallback model escalation should remain unchanged.
- Safety violations should not be retried.
- Timeouts should not be retried unless existing behavior says otherwise.
- Provider-specific details must stay behind `code_generator` and config.
- Normal tests must mock provider generation and must not require credentials.

**Acceptance criteria:**

- Existing single-file retry tests still pass.
- Multi-file execution path calls `code_generator.generate(...)`.
- Multi-file execution path calls `safety_checker.check(...)` before backend execution.
- Multi-file execution path calls `execution_backend.execute(...)` once per attempt.
- Backend router is still the only path to subprocess or Docker execution.
- Safety violations return a failure result without execution and without retry.
- Retry prompt behavior remains consistent for execution failures with stderr.
- Fallback model escalation remains bounded by existing config.

**Suggested tests:**

- Existing single-file compatibility.
- Multi-file execution path succeeds with mocked generation and mocked backend result.
- Safety check happens before backend execution.
- Backend router called once per generation attempt.
- Safety violation is not retried.
- Timeout is not retried if current behavior says not to retry.
- Execution stderr failure builds a retry prompt and then succeeds.

**Suggested verification command:**

```bash
uv run pytest tests/test_retry_handler.py tests/test_execution_backend.py
```

### Task 47: CLI Two-file Support

**Goal:** Add CLI support for named two-file inputs.

**Files likely touched:**

- Modify: `src/snapscript/interfaces/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_pipeline_cli_integration.py` only if existing integration coverage should be extended.

**Dependencies:** Task 46.

**Design notes:**

- Keep existing `--file PATH` behavior for single-file tasks.
- Add repeated `--file` support:

```bash
--file orders=orders.csv --file products=products.csv
```

- For multi-file mode, require logical names.
- Reject duplicate logical names.
- Reject invalid logical names.
- Reject more than two files in Phase 4A.
- Reject unnamed multi-file inputs such as `--file orders.csv --file products.csv`.
- Single-file `--file orders.csv` remains valid and should use the single-file path.
- CLI should call the same core pipeline as Streamlit.
- CLI should not duplicate merge logic.
- CLI should not parse natural-language join keywords.
- CLI should not call provider SDKs directly.
- CLI should not execute generated code directly.
- CLI errors should be concise and user-facing.

**Acceptance criteria:**

- `uv run python main.py --help` documents repeated named `--file` usage without removing single-file usage.
- Existing single-file CLI tests still pass.
- CLI accepts two named input files.
- CLI rejects duplicate names.
- CLI rejects invalid names.
- CLI rejects more than two files.
- CLI rejects unnamed multi-file inputs.
- CLI rejects unsupported file types through core validation.
- CLI calls the core high-level flow once for an accepted run.
- Mocked-provider join flow produces expected output through the sandbox.

**Suggested tests:**

- Existing single-file `--file input.csv` behavior.
- Two named files parse into two `InputFileSpec` values.
- Duplicate names produce a non-zero CLI error.
- Invalid logical name produces a non-zero CLI error.
- More than two files produce a non-zero CLI error.
- Unnamed multi-file inputs produce a non-zero CLI error.
- Unsupported file type is rejected.
- Mocked-provider join output works through the safe pipeline.

**Suggested verification command:**

```bash
uv run pytest tests/test_cli.py tests/test_pipeline_cli_integration.py
uv run python main.py --help
```

### Task 48: Streamlit Multi-upload Support

**Goal:** Add a simple two-file upload UI while keeping Streamlit thin.

**Files likely touched:**

- Modify: `src/snapscript/interfaces/web.py`
- Modify: `tests/test_streamlit_app.py`
- Modify: `tests/test_streamlit_pipeline_integration.py`

**Dependencies:** Task 46.

**Design notes:**

- Keep existing single-file upload workflow working.
- Add optional second upload path or an explicit two-file mode.
- Let users provide logical names for both files, for example `orders` and `products`.
- Validate suffix, size limit, duplicate names, missing names, and missing second file before accepting a Generate run.
- Reject more than two uploaded files in Phase 4A.
- Generate should remain the only action that calls provider/core execution.
- Uploading files or editing text must not call provider.
- Store uploaded bytes in session state only within existing local MVP constraints.
- Write uploaded files to temp paths only during an accepted run.
- Streamlit should call the core high-level flow, not provider SDKs or sandbox directly.
- Preview/download behavior should remain output-validation gated.
- Rate limiting should still happen before provider calls.
- Error display should remain redacted and concise.

**Acceptance criteria:**

- Existing single-file Streamlit tests still pass.
- Existing single-file upload workflow still works.
- Two-file mode accepts two supported uploaded files and two valid logical names.
- Duplicate names are rejected before provider calls.
- Missing names are rejected before provider calls.
- Missing second file is rejected in two-file mode before provider calls.
- Unsupported suffix and size limit failures occur before provider calls.
- Generate remains the only provider/core execution trigger.
- Uploaded files are written to temp paths only for accepted runs.
- Output preview/download only appears after successful output validation.
- Rate limiting still applies before provider calls.

**Suggested tests:**

- Session state initializes both single-file and two-file keys.
- Validation accepts two valid files and names.
- Validation rejects duplicate names.
- Validation rejects missing names.
- Validation rejects missing second file in two-file mode.
- Validation rejects unsupported suffix.
- No provider call occurs before Generate.
- Two-file temp input handling writes both files for an accepted run.
- Mocked-provider join output returns preview/download bytes only after success.

**Suggested verification command:**

```bash
uv run pytest tests/test_streamlit_app.py tests/test_streamlit_pipeline_integration.py
```

### Task 49: Multi-file Join Integration Tests

**Goal:** Add integration tests proving multi-file joins work through mocked provider plus real sandbox execution.

**Files likely touched:**

- Create: `tests/integration/test_multi_file_join.py`
- Optional create: `tests/integration/test_multi_file_join_real_provider.py`

**Dependencies:** Tasks 43 through 48.

**Fixtures:**

`orders.csv`:

```csv
order_id,pid,amount
1,p1,100
2,p2,200
3,p3,300
```

`products.csv`:

```csv
pid,product_name
p1,Keyboard
p2,Mouse
```

**Mocked-provider inner join test:**

User task:

```text
Please merge orders and products using the "pid" column with an inner join.
```

Mock generated code should read `INPUT_PATHS["orders"]`, `INPUT_PATHS["products"]`, and `OUTPUT_PATH`.

Expected result:

- 2 rows.
- Columns include `order_id`, `pid`, `amount`, and `product_name`.
- `p3` is dropped.

**Mocked-provider left join test:**

User task:

```text
Please merge orders and products using the "pid" column with a left join and keep all orders.
```

Expected result:

- 3 rows.
- Columns include `order_id`, `pid`, `amount`, and `product_name`.
- `p3` remains.
- `product_name` for `p3` is null or empty.

**Optional real-provider tests:**

- Put real-provider coverage in `tests/integration/test_multi_file_join_real_provider.py` or equivalent.
- Run only with `SNAPSCRIPT_REAL_PROVIDER=1`.
- Do not include real-provider tests in normal pytest behavior.
- These tests may verify that the LLM follows natural-language join instructions.

**Acceptance criteria:**

- Normal integration tests use mocked provider output.
- Normal integration tests do not require provider credentials.
- Normal integration tests do not require Docker.
- Integration tests validate pipeline wiring.
- Integration tests validate `INPUT_PATHS` path injection.
- Integration tests validate real sandbox execution through the default backend.
- Integration tests validate output validation.
- Mock generated code uses `INPUT_PATHS` in multi-file tests.
- Mock generated code does not use `INPUT_PATH` in multi-file tests.
- Mock generated code does not reference fixture source paths directly.
- Tests prove the sandbox path injection path is actually exercised.
- Tests do not depend on brittle keyword parsing in SnapScript.

**Suggested tests:**

- Assert mocked multi-file generated code imports or references `INPUT_PATHS` and `OUTPUT_PATH`.
- Assert mocked multi-file generated code does not reference `INPUT_PATH`.
- Assert mocked multi-file generated code does not contain fixture source paths or absolute temp source paths.
- Assert the integration path copies inputs into the sandbox workspace and reads them through `_snapscript_paths.py`.
- Assert direct fixture-path reads would fail the test setup or are absent from the generated code fixture.

**Suggested verification command:**

```bash
uv run pytest tests/integration/test_multi_file_join.py
```

### Task 50: Phase 4A Gate

**Goal:** Define acceptance criteria for Phase 4A completion.

**Dependencies:** Tasks 43 through 49.

**Gate criteria:**

- Full test suite passes.
- `env -u ANTHROPIC_API_KEY uv run pytest` passes.
- Normal pytest does not call a real provider.
- Normal pytest does not require Docker.
- Existing single-file CLI behavior still works.
- Existing single-file Streamlit behavior still works.
- Multi-file CLI works for two named CSV inputs.
- Multi-file Streamlit works for two named uploaded files.
- Multi-file prompt includes schemas for both files.
- Prompt does not contain real user paths.
- Generated code uses `INPUT_PATHS` and `OUTPUT_PATH`.
- Subprocess backend supports multi-file input.
- Docker backend supports multi-file input when explicitly enabled.
- Docker sandbox still mounts only the per-run temp workspace.
- `safety_checker` still runs before execution.
- `execution_backend` router still selects subprocess or Docker by config.
- Output validation still happens before download/copy-out.
- Multi-file join integration tests pass with mocked provider.
- Optional real-provider multi-file tests are opt-in only.
- No Phase 4A non-goals were added.

**Required verification commands:**

```bash
uv run pytest
env -u ANTHROPIC_API_KEY uv run pytest
uv run python main.py --help
uv run pytest tests/test_schema_inspector.py tests/test_prompt_builder.py
uv run pytest tests/test_sandbox_executor.py tests/test_docker_sandbox_executor.py tests/test_execution_backend.py tests/test_retry_handler.py
uv run pytest tests/test_cli.py tests/test_streamlit_app.py tests/test_streamlit_pipeline_integration.py
uv run pytest tests/integration/test_multi_file_join.py
```

**Optional Docker verification:**

```bash
docker build -t snapscript-sandbox:local docker/sandbox
SNAPSCRIPT_SANDBOX_BACKEND=docker uv run pytest tests/test_docker_sandbox_executor.py tests/test_execution_backend.py tests/test_retry_handler.py tests/integration/test_multi_file_join.py
```

**Optional real-provider verification:**

```bash
SNAPSCRIPT_REAL_PROVIDER=1 uv run pytest tests/integration/test_multi_file_join_real_provider.py
```

## 9. Verification Gates

Before implementation starts:

```bash
test -f docs/phase4_implementation_plan.md
```

During implementation, run the smallest relevant tests first:

```bash
uv run pytest tests/test_schema_inspector.py tests/test_prompt_builder.py
uv run pytest tests/test_sandbox_executor.py tests/test_docker_sandbox_executor.py tests/test_execution_backend.py tests/test_retry_handler.py
uv run pytest tests/test_cli.py tests/test_streamlit_app.py tests/test_streamlit_pipeline_integration.py
uv run pytest tests/integration/test_multi_file_join.py
```

Final non-optional gate:

```bash
uv run pytest
env -u ANTHROPIC_API_KEY uv run pytest
uv run python main.py --help
```

Optional Docker gate:

```bash
docker build -t snapscript-sandbox:local docker/sandbox
SNAPSCRIPT_SANDBOX_BACKEND=docker uv run pytest tests/test_docker_sandbox_executor.py tests/test_execution_backend.py tests/test_retry_handler.py tests/integration/test_multi_file_join.py
```

Optional real-provider gate:

```bash
SNAPSCRIPT_REAL_PROVIDER=1 uv run pytest tests/integration/test_multi_file_join_real_provider.py
```

## 10. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Multi-file support breaks single-file compatibility. | Preserve `INPUT_PATH` and existing single-file APIs/tests. Add `INPUT_PATHS = {"input": INPUT_PATH}` for single-file compatibility without removing old behavior. |
| Prompt becomes ambiguous about file roles. | Require logical names for multi-file CLI/UI inputs and show named schema blocks. |
| Generated code hardcodes paths. | Prompt explicitly requires `INPUT_PATHS`; tests assert no real paths appear in prompts or `_snapscript_paths.py`. |
| Interfaces duplicate merge logic. | CLI and Streamlit only collect files/task and call the core high-level pipeline. |
| Custom keyword parsing becomes brittle. | Let the LLM interpret the task; SnapScript provides schemas and safe input abstractions. |
| Docker path handling regresses. | Use shared workspace/path helper where appropriate and test subprocess plus Docker path behavior. |
| Real-provider tests become flaky or expensive. | Keep them opt-in with `SNAPSCRIPT_REAL_PROVIDER=1`. |
| More-than-two-file support slips into Phase 4A. | Enforce a two-file limit in CLI/UI validation and tests; document unlimited multi-file support as future work only. |
| Output validation is bypassed during interface changes. | Keep preview/download/copy-out gated on the existing validated `ExecutionResult.success` behavior. |
| Safety expectations drift during prompt changes. | Keep AST safety checks mandatory before execution and run safety/sandbox tests as part of the gate. |

## 11. What Not To Do

- Do not implement unlimited multi-file support in Phase 4A.
- Do not design the feature as only "merge two CSV files"; design it as named multi-file input support with a two-file Phase 4A limit.
- Do not add a relational query planner.
- Do not parse natural-language join instructions with custom SnapScript keyword logic.
- Do not synthesize merge code in CLI or Streamlit.
- Do not bypass `prompt_builder`.
- Do not bypass `code_generator`.
- Do not bypass `safety_checker`.
- Do not bypass `execution_backend`.
- Do not execute generated code directly from CLI or Streamlit.
- Do not call provider SDKs directly from CLI or Streamlit.
- Do not inject real user paths into prompts or generated code.
- Do not use `str.replace()` or similar string substitution for file path injection.
- Do not replace `_snapscript_paths.py`; extend it.
- Do not mount the repo root into Docker.
- Do not mount the user's home directory into Docker.
- Do not weaken Docker restrictions such as network-disabled mode, memory limits, CPU limits, or PID limits.
- Do not log raw uploaded datasets, full prompts, generated code, API keys, `.env` contents, secrets, environment variables, or full tracebacks by default.
- Do not make Docker required for normal `uv run pytest`.
- Do not make provider credentials required for normal `uv run pytest`.
- Do not include real-provider tests in normal pytest.
- Do not add database connectors, cloud execution, auth, billing, dashboards, persistent project history, or data visualization as part of Phase 4A.
