# Phase 1 CLI Pipeline Implementation Plan

> Recommended workflow: implement tasks incrementally and verify each task before moving to the next. Use the verification commands and acceptance criteria as execution gates.

**Goal:** Build a minimal end-to-end SnapScript CLI pipeline for single CSV/Excel tasks: inspect schema -> build prompt -> generate code -> safety-check -> sandbox-execute -> validate output.

**Architecture:** Phase 1 is CLI plus interface-agnostic core only. The core owns schema inspection, prompt construction, provider-aware code generation, AST safety checks, subprocess sandbox execution, and retry decisions; the CLI only parses input and formats output. Generated code is never trusted until it passes `safety_checker` and runs through `sandbox_executor`.

**Tech Stack:** Python 3.10+, uv, pandas, openpyxl, chardet, rich, python-dotenv, and an LLM provider SDK (Anthropic SDK as the initial default implementation).

---

## Scope

- In scope: CLI, core modules, single CSV/Excel processing, configured LLM provider, subprocess sandbox, safety checks, output validation, retry handling, CLI gate tasks.
- Out of scope: Streamlit, Docker, Tauri, web UI, database, auth, visualization, cloud execution, multi-file workflows.
- Phase 2 Streamlit starts only after 8/10 CLI gate tasks pass on first attempt without retry.

## File Map

- `main.py`: root app entrypoint, delegates to CLI.
- `src/snapscript/__init__.py`: package marker.
- `src/snapscript/__main__.py`: `python -m snapscript` entrypoint.
- `src/snapscript/config.py`: frozen app config, provider/model settings, limits.
- `src/snapscript/core/models.py`: all shared dataclasses.
- `src/snapscript/core/schema_inspector.py`: CSV/Excel schema extraction.
- `src/snapscript/core/prompt_builder.py`: `PromptPayload` assembly.
- `src/snapscript/core/code_generator.py`: configured LLM provider call and code cleanup.
- `src/snapscript/core/safety_checker.py`: AST safety scan.
- `src/snapscript/core/sandbox_executor.py`: subprocess execution, `_snapscript_paths.py`, output validation and copy-out.
- `src/snapscript/core/retry_handler.py`: retry decisions and fallback model escalation.
- `src/snapscript/interfaces/cli.py`: argparse/rich CLI adapter.
- `src/snapscript/prompts/system.txt`: code generation system prompt.
- `src/snapscript/prompts/retry.txt`: retry prompt template.
- `tests/fixtures/unit/malicious_code.py`: known unsafe snippets.
- `tests/fixtures/integration/`: existing 10 CLI gate fixtures.

## Foundation Tasks

### Task 1: Package Skeleton ✅

**Goal:** Create importable package and CLI entrypoints.

**Files touched:**
- Create: `src/snapscript/__init__.py`
- Create: `src/snapscript/__main__.py`
- Create: `src/snapscript/core/__init__.py`
- Create: `src/snapscript/interfaces/__init__.py`
- Modify: `main.py`

**Dependencies:** None.

**Acceptance criteria:**
- `uv run python main.py --help` reaches CLI help.
- `uv run python -m snapscript --help` reaches the same CLI help.
- No Streamlit imports.

**Suggested verification command:**
```bash
uv run python main.py --help
uv run python -m snapscript --help
```

### Task 2: App Config ✅

**Goal:** Centralize provider/model settings and execution limits.

**Files touched:**
- Create: `src/snapscript/config.py`
- Test: `tests/test_config.py`

**Dependencies:** Task 1.

**Acceptance criteria:**
- `AppConfig` is `@dataclass(frozen=True)`.
- Includes provider-aware fields such as `llm_provider`, `default_model`, `fallback_model`.
- Anthropic/Claude is allowed as Phase 1 default, but business logic reads names from config.
- Includes timeout, retry, schema, output, and safety limits.
- No API keys are stored in config constants.

**Suggested verification command:**
```bash
uv run pytest tests/test_config.py
```

### Task 3: Core Models ✅

**Goal:** Define shared dataclasses once.

**Files touched:**
- Create: `src/snapscript/core/models.py`
- Test: `tests/test_models.py`

**Dependencies:** Task 1.

**Acceptance criteria:**
- Defines `ColumnInfo`, `SchemaReport`, `PromptPayload`, `GeneratedScript`, `SafetyResult`, `ExecutionResult`.
- `PromptPayload` contains separate `system_prompt: str` and `user_prompt: str` fields.
- `ExecutionResult.success` is the single source of execution success.
- Dataclasses are imported by other modules, not redefined.
- Return models include enough metadata for CLI display without coupling core to rich/argparse.

**Suggested verification command:**
```bash
uv run pytest tests/test_models.py
```

### Task 4: Prompt Files ✅

**Goal:** Add minimal system and retry prompt templates.

**Files touched:**
- Create: `src/snapscript/prompts/system.txt`
- Create: `src/snapscript/prompts/retry.txt`
- Optionally create later: `src/snapscript/prompts/CHANGELOG.md`

**Dependencies:** Task 1.

**Acceptance criteria:**
- System prompt requires generated scripts to import `INPUT_PATH` and `OUTPUT_PATH` from `_snapscript_paths`.
- System prompt says output must be written to `OUTPUT_PATH`.
- System prompt forbids shell execution, network access, `exec`, `eval`, and unsafe imports.
- System prompt instructs chunked processing for large-file transformations where applicable.
- Retry prompt includes previous error and previous code placeholders.

**Suggested verification command:**
```bash
test -f src/snapscript/prompts/system.txt
test -f src/snapscript/prompts/retry.txt
```

## Core Pipeline Tasks

### Task 5: `schema_inspector.py` ✅

**Goal:** Extract safe schema summaries from CSV/Excel without reading whole large files.

**Files touched:**
- Create: `src/snapscript/core/schema_inspector.py`
- Test: `tests/test_schema_inspector.py`
- Fixtures: use existing `tests/fixtures/integration/*.csv`

**Dependencies:** Tasks 2, 3.

**Acceptance criteria:**
- Public API: `inspect(path: Path, sheet: str | None = None) -> SchemaReport`.
- Supports `.csv`, `.xlsx`, `.xls`.
- Reads at most `schema_inspect_rows`.
- Captures filename, file type, row count, columns, sample rows, file size, encoding, sheet names.
- Truncates column names to 100 chars before prompt use.
- Raises typed exceptions for missing, unsupported, unreadable, or too-large files.

**Suggested verification command:**
```bash
uv run pytest tests/test_schema_inspector.py
```

### Task 6: `prompt_builder.py` ✅

**Goal:** Convert task + schema into a `PromptPayload` with separate system and user prompts.

**Files touched:**
- Create: `src/snapscript/core/prompt_builder.py`
- Test: `tests/test_prompt_builder.py`

**Dependencies:** Tasks 3, 4, 5.

**Acceptance criteria:**
- Public API returns `PromptPayload`, not a tuple.
- `PromptPayload.system_prompt` contains the system instructions.
- `PromptPayload.user_prompt` contains schema, task description, and output requirement.
- Schema content is wrapped in `<schema>...</schema>`.
- User task appears outside the schema block.
- `INPUT_PATH` and `OUTPUT_PATH` are variable names only; no real paths are inserted.
- Prompt includes output format requirement.
- Prompt truncates samples if token budget is exceeded.

**Suggested verification command:**
```bash
uv run pytest tests/test_prompt_builder.py
```

### Task 7: `code_generator.py` ✅

**Goal:** Generate clean Python from `PromptPayload` via the configured LLM provider.

**Files touched:**
- Create: `src/snapscript/core/code_generator.py`
- Test: `tests/test_code_generator.py`

**Dependencies:** Tasks 2, 3, 4, 6.

**Acceptance criteria:**
- Public API: `generate(prompt: PromptPayload, model: str | None = None) -> GeneratedScript`.
- Uses `prompt.system_prompt` and `prompt.user_prompt` as separate provider inputs.
- Uses configured provider SDK; Anthropic is initial default but architecture is not named Claude-only.
- Reads provider/model names from `AppConfig`.
- Uses `temperature=0`.
- Strips markdown fences and non-code prose.
- Validates generated code with `ast.parse()`.
- Does not safety-check or execute code itself.
- Does not log full prompts, generated code, file contents, or API keys.

**Suggested verification command:**
```bash
uv run pytest tests/test_code_generator.py
```

### Task 8: `safety_checker.py` ✅

**Goal:** Reject unsafe generated code before sandbox execution.

**Files touched:**
- Create: `src/snapscript/core/safety_checker.py`
- Create: `tests/fixtures/unit/malicious_code.py`
- Test: `tests/test_safety_checker.py`

**Dependencies:** Tasks 2, 3.

**Acceptance criteria:**
- Public API: `check(code: str) -> SafetyResult`.
- Blocks unsafe imports: `os`, `sys`, `subprocess`, network modules, `pickle`, `ctypes`, `importlib`, etc.
- Blocks unsafe calls: `exec`, `eval`, `compile`, `__import__`, `globals`, `locals`, `getattr`, `setattr`, `delattr`.
- Does not globally block `open()`.
- Blocks `open()` when literal first arg contains `/`, `..`, or Windows absolute path shape.
- Allows normal pandas reads/writes using `INPUT_PATH` and `OUTPUT_PATH`.

**Suggested verification command:**
```bash
uv run pytest tests/test_safety_checker.py
```

### Task 9: `sandbox_executor.py` ✅

**Goal:** Execute generated code in a temp workspace, validate output, and copy validated output to the requested destination.

**Files touched:**
- Create: `src/snapscript/core/sandbox_executor.py`
- Test: `tests/test_sandbox_executor.py`

**Dependencies:** Tasks 2, 3, 8.

**Acceptance criteria:**
- Public API: `execute(code: str, input_path: Path, output_path: Path) -> ExecutionResult`.
- Copies input file into temp workspace.
- Writes `_snapscript_paths.py` with `INPUT_PATH` and `OUTPUT_PATH`.
- Writes generated code unchanged to `script.py`; no `str.replace()`.
- Runs subprocess with timeout and workspace `cwd`.
- Captures stdout, stderr, exit code, duration.
- Validates output by reading first row with pandas.
- Returns `success=False` if output is missing, empty, or unreadable.
- Copies the validated output file from the temp workspace to the requested `output_path` before cleanup.
- Cleans temp workspace without deleting the user's source input.

**Suggested verification command:**
```bash
uv run pytest tests/test_sandbox_executor.py
```

### Task 10: `retry_handler.py` ✅

**Goal:** Decide when to retry and when to escalate to fallback model.

**Files touched:**
- Create: `src/snapscript/core/retry_handler.py`
- Test: `tests/test_retry_handler.py`

**Dependencies:** Tasks 2, 3, 6, 7, 8, 9.

**Acceptance criteria:**
- Retries execution errors with Python traceback.
- Does not retry safety violations, timeouts, or auth/config errors.
- Caps total model calls at 3 per user task.
- Final retry passes the existing `PromptPayload` retry prompt and `config.fallback_model` to `code_generator.generate(...)`.
- Builds retry prompt using `prompts/retry.txt`.
- Does not call Streamlit or CLI code.

**Suggested verification command:**
```bash
uv run pytest tests/test_retry_handler.py
```

### Task 11: `interfaces/cli.py` ✅

**Goal:** Wire the core pipeline into a usable CLI.

**Files touched:**
- Create: `src/snapscript/interfaces/cli.py`
- Modify: `src/snapscript/__main__.py`
- Modify: `main.py`
- Test: `tests/test_cli.py`

**Dependencies:** Tasks 5-10.

**Acceptance criteria:**
- Supports `task`, `--file/-f`, `--output/-o`, `--sheet/-s`, `--dry-run`, `--yes/-y`, `--show-code`, `--api-key`, `--verbose`.
- Uses argparse and rich only in interface layer.
- Validates input path/extension before API call.
- Shows schema summary, generation metadata, safety result, execution result.
- Asks for confirmation unless `--yes` or `--dry-run`.
- Maps core exceptions to user-facing exit codes/messages.
- Does not import Streamlit.
- Does not place interface logic in core.

**Suggested verification command:**
```bash
uv run pytest tests/test_cli.py
uv run python main.py --help
```

## Safety And Testing Tasks

### Task 12: Malicious Fixtures And Safety Regression Suite ✅

**Goal:** Keep known unsafe patterns explicit and tested.

**Files touched:**
- Create: `tests/fixtures/unit/malicious_code.py`
- Modify/Test: `tests/test_safety_checker.py`

**Dependencies:** Task 8.

**Acceptance criteria:**
- Fixture includes unsafe imports, shell execution, dynamic import, `exec`, `eval`, `getattr`, absolute `open`, traversal `open`.
- Tests also include allowed examples: pandas import, `pd.read_csv(INPUT_PATH)`, `df.to_csv(OUTPUT_PATH)`, relative `open("notes.txt")`.
- Safety tests cover false positives and false negatives.

**Suggested verification command:**
```bash
uv run pytest tests/test_safety_checker.py
```

### Task 13: Sandbox Output Validation Tests ✅

**Goal:** Prove "script exited 0" is not enough.

**Files touched:**
- Modify/Test: `tests/test_sandbox_executor.py`

**Dependencies:** Task 9.

**Acceptance criteria:**
- Success when valid CSV output has at least one row.
- Failure when output file is missing.
- Failure when output file is empty.
- Failure when output file is unreadable/corrupt.
- Success copies the validated temp output file to the requested `output_path`.
- Failure result includes useful stderr or error message.
- Test asserts `_snapscript_paths.py` exists during execution via a script that imports it.

**Suggested verification command:**
```bash
uv run pytest tests/test_sandbox_executor.py
```

### Task 14: Minimal End-To-End CLI Test Without Real API ✅

**Goal:** Verify pipeline wiring without spending API calls.

**Files touched:**
- Create: `tests/test_pipeline_cli_integration.py`

**Dependencies:** Tasks 5-11.

**Acceptance criteria:**
- Mocks `code_generator.generate(...)` to return safe known code.
- Runs CLI against `tests/fixtures/integration/task_02_orders.csv`.
- Produces output file.
- Output rows all satisfy `amount > 1000`.
- Confirms safety check and sandbox execution are still used.

**Suggested verification command:**
```bash
uv run pytest tests/test_pipeline_cli_integration.py
```

## CLI Gate Tasks

Use existing fixtures in `tests/fixtures/integration/`. These are the Day 7 runnable gate set and Days 8-10 prompt iteration set.

### Task 15: Define Gate Task Assertions ✅

**Goal:** Turn the existing 10 fixtures into executable assertions.

**Files touched:**
- Create: `tests/integration/test_cli_gate_tasks.py`
- Use: `tests/fixtures/integration/FIXTURE_MANIFEST.json`

**Dependencies:** Tasks 11, 14.

**Acceptance criteria:**
- Each task has an input fixture, natural-language prompt, and expected output property.
- Tests can run in mocked-provider mode for pipeline validation.
- Real-provider runs are opt-in via env var, for prompt iteration.
- Default test runs must not call a real LLM provider.

**Suggested verification command:**
```bash
uv run pytest tests/integration/test_cli_gate_tasks.py
```

| Task | Input fixture | Natural-language prompt | Expected output property |
|------|---------------|-------------------------|--------------------------|
| 1 | `task_01_customers.csv` | "Remove duplicate rows by email, keeping the row with the latest created_at date." | 800 rows, 800 unique emails; latest `alice@test.com` kept |
| 2 | `task_02_orders.csv` | "Keep only orders where amount is greater than 1000." | 383 rows; every `amount > 1000` |
| 3 | `task_03_contacts.csv` | "Create a full_name column by combining first_name and last_name." | 200 rows; `full_name` exists; first row `Eve Evans` |
| 4 | `task_04_logs.csv` | "Convert event_date from MM/DD/YYYY to YYYY-MM-DD." | 300 rows; row 0 date is `2024-01-15` |
| 5 | `task_05_mixed.csv` | "Convert price to numeric and drop rows with invalid prices." | 380 rows; price is numeric |
| 6 | `task_06_sparse.csv` | "Fill missing notes with 'No notes'." | 300 rows; 0 null notes; exactly 100 filled |
| 7 | `task_07_status.csv` | "Replace status value old with archived." | 500 rows; no `old`; 143 `archived` |
| 8 | `task_08_scores.csv` | "Sort by score descending and keep the top 10 rows." | 10 rows; scores descending; top score 100 |
| 9 | `task_09_events.csv` | "Count rows per event_type." | 5 rows; counts sum to 2000 |
| 10 | `task_10_big.csv` | "Filter rows where region equals West." | 49,983 rows; completes within 25s target |

## Verification Gates

### Task 16: Gate - Minimal Working Path ✅

**Goal:** Confirm the core CLI pipeline works before hardening.

**Dependencies:** Tasks 1-11.

**Must pass:**
- Config/model/schema/prompt/codegen/safety/sandbox/retry/CLI unit tests.
- Mocked end-to-end CLI test.
- No Streamlit imports in `src/snapscript/core/`.

**Suggested verification command:**
```bash
uv run pytest tests/test_config.py tests/test_models.py tests/test_schema_inspector.py tests/test_prompt_builder.py tests/test_code_generator.py tests/test_safety_checker.py tests/test_sandbox_executor.py tests/test_retry_handler.py tests/test_cli.py tests/test_pipeline_cli_integration.py
```

### Task 17: Gate - Safety Hardening Complete ✅

**Goal:** Confirm generated code cannot skip static safety or output validation.

**Dependencies:** Tasks 8, 9, 12, 13.

**Must pass:**
- Malicious fixtures blocked.
- Legitimate pandas snippets allowed.
- `_snapscript_paths.py` injection tested.
- No `str.replace()` path injection.
- Missing/empty/unreadable outputs return failure.
- Validated temp output is copied to requested `output_path` before cleanup.

**Suggested verification command:**
```bash
uv run pytest tests/test_safety_checker.py tests/test_sandbox_executor.py
```

### Task 18: Gate - Ready For Days 8-10 Prompt Iteration

**Goal:** Day 7 readiness.

**Dependencies:** Tasks 1-17.

**Must pass:**
- `uv run pytest` passes.
- `uv run python main.py --help` works.
- All 10 CLI gate tasks are runnable in mocked-provider mode.
- Real-provider mode is available but opt-in.
- Normal `uv run pytest` does not call a real LLM provider.
- Prompt changes can be documented in `src/snapscript/prompts/CHANGELOG.md`.

**Suggested verification command:**
```bash
uv run pytest
uv run python main.py --help
uv run pytest tests/integration/test_cli_gate_tasks.py
```

### Task 19: Gate - Prompt Iteration Complete

**Goal:** Finish Days 8-10.

**Dependencies:** Task 18.

**Must pass:**
- Run all 10 CLI gate tasks with real provider only through explicit opt-in.
- Never run real-provider gate tests by default in normal `uv run pytest`.
- Record failure modes after each opt-in real-provider run.
- Iterate only `src/snapscript/prompts/system.txt` unless a true code bug is found.
- Document each prompt change and what it fixed.
- Achieve at least 8/10 first-attempt passes without retry.

**Suggested opt-in verification command:**
```bash
SNAPSCRIPT_RUN_REAL_LLM=1 uv run pytest tests/integration/test_cli_gate_tasks.py
```

### Task 20: Gate - Before Phase 2 Streamlit

**Goal:** Enforce no premature web work.

**Dependencies:** Task 19.

**Must pass before any Streamlit task starts:**
- 8/10 CLI gate tasks pass on first attempt with real provider.
- Full test suite passes.
- CLI remains usable for all Phase 1 flows.
- Core remains interface-agnostic.
- Safety checker and sandbox executor remain mandatory in the execution path.
- No unresolved Phase 1 safety blockers.
- Normal `uv run pytest` still does not call a real LLM provider.

**Suggested verification command:**
```bash
uv run pytest
SNAPSCRIPT_RUN_REAL_LLM=1 uv run pytest tests/integration/test_cli_gate_tasks.py
```
