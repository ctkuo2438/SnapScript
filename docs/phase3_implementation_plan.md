# Phase 3 Hardening / Real Product Implementation Plan

> Recommended workflow: implement tasks incrementally and verify each task before moving to the next. Phase 3A Docker sandbox hardening should happen before any Tauri or MCP work.

**Goal:** Turn SnapScript from a local CLI + Streamlit MVP into a safer, more product-like tool by replacing subprocess-only sandbox execution with Docker container isolation, preparing a real desktop app path using Tauri, and optionally exposing SnapScript as an MCP server.

**Architecture:** Phase 3 keeps the Phase 1 and Phase 2 architecture boundary intact. `src/snapscript/core/` remains interface-agnostic. CLI, Streamlit, future Tauri, and future MCP interfaces must all call the same safe core pipeline. Generated code must never run directly from an interface layer; it must flow through prompt building, code generation, `safety_checker`, the selected sandbox backend, output validation, retry handling, and safe audit logging.

**Tech Stack:** Python 3.10+, uv, pandas, openpyxl, chardet, existing SnapScript core modules, Docker for explicit sandbox hardening, Tauri as a future desktop shell, and MCP as a future local integration interface.

---

## 1. Phase 3 Goals

- Add a Docker sandbox backend as an additional runtime isolation layer.
- Preserve the existing subprocess sandbox backend during migration.
- Keep `safety_checker` mandatory before any sandbox backend.
- Route execution through a backend selector used by `retry_handler.run(...)`.
- Keep normal `uv run pytest` free of Docker and real-provider requirements.
- Keep CLI and Streamlit behavior working while Docker is opt-in.
- Define a practical Tauri desktop path without rewriting the Python core in Rust.
- Define an optional MCP server path that exposes SnapScript through safe tools and resources.
- Preserve metadata-only audit logging by default.

## 2. Non-goals

Phase 3 does not include:

- Cloud execution.
- Hosted backend service.
- Auth or user accounts.
- Database-backed history.
- Billing.
- Multi-user workspace.
- Team collaboration features.
- Dashboard or observability product.
- Persistent project history beyond local audit metadata.
- Data visualization or chart generation.
- Multi-file workflows.
- Rewriting the Python core in Rust.
- Removing the subprocess backend immediately.
- Weakening `safety_checker`.
- Logging raw uploaded datasets, prompts, generated code, API keys, or secrets by default.

## 3. Current Project History

Phase 1 built the CLI/core pipeline:

```text
schema inspection
  -> prompt building
  -> code generation
  -> safety checking
  -> sandbox execution
  -> output validation
  -> retry handling
```

Phase 2 added a thin Streamlit UI on top of the existing safe core pipeline:

```text
Streamlit UI
  -> upload/task validation
  -> rate limiting
  -> schema_inspector.inspect(...)
  -> prompt_builder.build(...)
  -> retry_handler.run(...)
  -> safety_checker.check(...)
  -> sandbox_executor.execute(...)
  -> preview/download
  -> safe audit event
```

Task 31 added local JSONL audit logging for accepted Streamlit Generate runs. Audit logs are metadata-only by default and must remain local and gitignored.

## 4. Architecture Boundary

All Phase 3 work must preserve these rules:

- `src/snapscript/core/` must not import Streamlit, Tauri, MCP server libraries, `argparse`, `rich`, or UI state.
- Interface layers may call core entrypoints, but generated code execution stays behind core execution APIs.
- CLI, Streamlit, Tauri, and MCP must not directly call provider SDKs.
- CLI, Streamlit, Tauri, and MCP must not directly call `sandbox_executor.execute(...)` or `docker_sandbox_executor.execute(...)` once the backend router exists.
- `retry_handler.run(...)` remains the high-level safe execution path.
- `safety_checker.check(...)` always runs before either sandbox backend.
- Docker sandboxing does not replace AST safety checking; it adds runtime isolation after static checks.
- Audit logging must not change execution behavior and must stay best-effort unless a later task explicitly changes that.

Target Phase 3A execution flow:

```text
CLI / Streamlit / Tauri / MCP
  -> schema_inspector.inspect(...)
  -> prompt_builder.build(...)
  -> retry_handler.run(...)
      -> code_generator.generate(...)
      -> safety_checker.check(...)
      -> execution_backend.execute(...)
          -> sandbox_executor.execute(...)
          -> docker_sandbox_executor.execute(...)
      -> audit metadata where applicable
```

## 5. Proposed File Structure

Phase 3A Docker sandbox hardening:

- Create: `src/snapscript/core/docker_sandbox_executor.py`
- Create: `src/snapscript/core/execution_backend.py`
- Modify: `src/snapscript/core/retry_handler.py`
- Modify: `src/snapscript/config.py`
- Optional modify: `src/snapscript/core/models.py` only to extend existing dataclasses with defaulted metadata fields.
- Create: `tests/test_docker_sandbox_executor.py`
- Create: `tests/test_execution_backend.py`
- Modify: `tests/test_retry_handler.py`
- Create: `docker/sandbox/Dockerfile`
- Create: `docker/sandbox/requirements.txt`
- Create: `docs/docker_sandbox.md`

Phase 3B Tauri desktop path:

- Create or modify: `docs/tauri_desktop_architecture.md`
- Modify: `src/snapscript/interfaces/cli.py` or create a dedicated JSON command adapter under `src/snapscript/interfaces/`.
- Optional create: `src/snapscript/interfaces/json_command.py`
- Create or modify: `tests/test_json_command_interface.py`
- Optional create later: Tauri project files under a reviewed desktop directory.

Phase 3C MCP server:

- Create: `src/snapscript/interfaces/mcp_server.py`
- Create: `tests/test_mcp_server.py`
- Create: `docs/mcp_server.md`

Do not add these files before their associated task. Each task should stay independently reviewable.

## 6. Phase 3A: Docker Sandbox Hardening

Phase 3A is the first and most important part of Phase 3.

The current subprocess sandbox is useful for the local MVP, but it is not enough for real product hardening. A subprocess shares the host Python runtime and relies heavily on AST checks plus temporary working directories. That is acceptable for proving the workflow, but a product path needs stronger runtime isolation. Docker should provide a container boundary, controlled mounts, network denial, memory and CPU limits, PID limits, and a cleaner separation from arbitrary host paths.

Docker sandboxing is not a replacement for `safety_checker`. The static AST check remains the first layer of defense. Docker becomes the second runtime isolation layer after the same safety check has passed.

### Task 32: Docker Sandbox Executor Skeleton

**Goal:** Add a Docker-based sandbox executor without removing the existing subprocess executor.

**Files likely touched:**
- Create: `src/snapscript/core/docker_sandbox_executor.py`
- Create: `tests/test_docker_sandbox_executor.py`
- Modify: `src/snapscript/config.py` if needed.
- Modify: `src/snapscript/core/models.py` only if existing models need defaulted metadata extension.

**Dependencies:** Task 31 complete.

**Acceptance criteria:**
- Docker executor exposes the same public contract shape as `sandbox_executor.execute(code, input_path, output_path) -> ExecutionResult`.
- Docker executor returns `ExecutionResult` from `src/snapscript/core/models.py`.
- Generated code is written unchanged to `script.py`.
- `_snapscript_paths.py` is still used for `INPUT_PATH` and `OUTPUT_PATH` injection.
- Input file is copied into a temporary workspace before container execution.
- Output is validated before being copied out to the requested output path.
- Missing, empty, or unreadable output returns `success=False`.
- Docker executor captures stdout, stderr, exit code, duration, and output files consistently with the subprocess executor.
- Docker executor does not call provider SDKs.
- Docker executor does not call `code_generator.generate(...)`.
- Docker executor does not call or bypass `safety_checker`; it assumes the caller already checked safety.
- Unit tests cover command construction, workspace layout, path module creation, output validation, and failure handling without requiring Docker where possible.

**Suggested verification command:**
```bash
uv run pytest tests/test_docker_sandbox_executor.py
uv run pytest tests/test_sandbox_executor.py
```

### Task 33: Sandbox Backend Configuration

**Goal:** Allow SnapScript to choose between subprocess and Docker sandbox backends.

**Suggested config fields:**
- `sandbox_backend: "subprocess" | "docker"`
- `docker_image`
- `docker_timeout_seconds`
- `docker_memory_limit`
- `docker_cpu_limit`
- `docker_network_disabled`

**Files likely touched:**
- Modify: `src/snapscript/config.py`
- Create or modify: `tests/test_config.py`
- Create or modify: `tests/test_execution_backend.py`

**Dependencies:** Task 32.

**Acceptance criteria:**
- Default sandbox backend may remain `subprocess` initially to avoid breaking normal tests.
- Docker backend can be enabled through config or environment variable, such as `SNAPSCRIPT_SANDBOX_BACKEND=docker`.
- Invalid backend values fail early with a clear typed error.
- Docker-specific tests are skipped unless Docker is available or explicitly enabled.
- Normal `uv run pytest` does not require Docker.
- Normal `uv run pytest` does not require `ANTHROPIC_API_KEY`.
- Existing subprocess behavior remains the default and remains tested.

**Suggested verification command:**
```bash
uv run pytest tests/test_config.py tests/test_execution_backend.py
env -u ANTHROPIC_API_KEY uv run pytest
```

### Task 34: Minimal Sandbox Docker Image

**Goal:** Create a minimal runtime image for generated pandas scripts.

**Files likely touched:**
- Create: `docker/sandbox/Dockerfile`
- Create: `docker/sandbox/requirements.txt`
- Create: `docs/docker_sandbox.md`

**Dependencies:** Tasks 32 and 33.

**Acceptance criteria:**
- Image includes pandas, openpyxl, chardet, and only needed runtime dependencies.
- Image does not include API keys or `.env` files.
- Image does not include provider SDKs unless a later reviewed task proves they are required in the sandbox. Generated scripts should not call providers.
- Image can run generated `script.py`.
- Image supports CSV, `.xlsx`, and `.xls` outputs where current SnapScript supports them.
- Container runs as non-root if feasible.
- Build command is documented.
- Runtime command examples are documented without secrets.
- `.dockerignore` is added if needed to prevent copying logs, `.env`, caches, fixtures with sensitive local data, or unrelated repo files.

**Suggested verification command:**
```bash
docker build -t snapscript-sandbox:local docker/sandbox
SNAPSCRIPT_SANDBOX_BACKEND=docker uv run pytest tests/test_docker_sandbox_executor.py
```

### Task 35: Docker Runtime Restrictions

**Goal:** Define and test secure Docker run options.

**Required runtime restrictions:**
- `--network none`
- `--memory` limit
- `--cpus` limit
- `--pids-limit`
- `--read-only` if feasible
- Temporary workspace mount only
- No mount of the repo root
- No mount of the user's home directory
- Timeout handling outside the container

**Files likely touched:**
- Modify: `src/snapscript/core/docker_sandbox_executor.py`
- Modify: `tests/test_docker_sandbox_executor.py`
- Modify: `docs/docker_sandbox.md`

**Dependencies:** Task 34.

**Acceptance criteria:**
- Docker command includes network-disabled mode by default.
- Generated code cannot access the network.
- Generated code cannot access arbitrary host paths.
- Generated code can only read the copied input and write output inside the temp workspace.
- Timeout failures return `ExecutionResult(success=False)`.
- Memory failures return `ExecutionResult(success=False)`.
- Non-zero exit returns `ExecutionResult(success=False)`.
- Missing output returns `ExecutionResult(success=False)`.
- Empty output returns `ExecutionResult(success=False)`.
- Unreadable output returns `ExecutionResult(success=False)`.
- Error messages are useful but redacted.
- Tests prove command-line options are included and failure modes are mapped without leaking secrets.

**Suggested verification command:**
```bash
SNAPSCRIPT_SANDBOX_BACKEND=docker uv run pytest tests/test_docker_sandbox_executor.py
uv run pytest tests/test_safety_checker.py tests/test_sandbox_executor.py
```

### Task 36: Execution Backend Router

**Goal:** Route `retry_handler` through a backend selector while preserving the safe execution path.

**Likely file:**
- Create: `src/snapscript/core/execution_backend.py`
- Modify: `src/snapscript/core/retry_handler.py`
- Create: `tests/test_execution_backend.py`
- Modify: `tests/test_retry_handler.py`

**Design:**
```text
retry_handler.run(...)
  -> code_generator.generate(...)
  -> safety_checker.check(...)
  -> execution_backend.execute(...)
      -> subprocess sandbox
      -> docker sandbox
```

**Dependencies:** Tasks 32-35.

**Acceptance criteria:**
- CLI and Streamlit still call `retry_handler.run(...)`.
- `retry_handler.run(...)` remains the high-level execution path.
- `safety_checker.check(...)` always runs before `execution_backend.execute(...)`.
- `execution_backend.execute(...)` selects subprocess or Docker using `AppConfig`.
- Existing subprocess behavior remains tested.
- Docker backend is selected only by config or explicit environment override.
- No interface layer directly calls `docker_sandbox_executor`.
- No interface layer directly calls `sandbox_executor.execute(...)` after this router exists.
- Retry behavior and fallback model escalation remain unchanged.
- Normal pytest remains no-provider and no-Docker by default.

**Suggested verification command:**
```bash
uv run pytest tests/test_execution_backend.py tests/test_retry_handler.py
uv run pytest tests/test_pipeline_cli_integration.py tests/test_streamlit_pipeline_integration.py
SNAPSCRIPT_SANDBOX_BACKEND=subprocess uv run pytest
```

## 7. Phase 3B: Tauri Desktop App Path

Tauri should be an interface layer only. Do not rewrite the Python core in Rust. The desktop app should call a stable local command or API boundary that delegates to SnapScript's existing Python core.

Target desktop architecture:

```text
Tauri UI
  -> local SnapScript command or local API
      -> snapscript core
          -> schema_inspector
          -> prompt_builder
          -> retry_handler
              -> code_generator
              -> safety_checker
              -> selected sandbox backend
          -> audit_logger
```

Phase 3B should start only after Phase 3A has a working backend selector. A desktop shell without the hardened sandbox path risks making a more polished interface for an insufficiently hardened runtime.

### Task 37: Define Desktop App Boundary

**Goal:** Document the Tauri architecture boundary.

**Files likely touched:**
- Create: `docs/tauri_desktop_architecture.md`
- Optional modify: `docs/phase3_implementation_plan.md` to record decisions.

**Dependencies:** Task 36.

**Acceptance criteria:**
- Tauri does not execute generated code directly.
- Tauri does not call provider SDKs directly.
- Tauri does not duplicate schema, prompt, retry, safety, sandbox, or audit logic.
- Core remains Python and interface-agnostic.
- Local desktop integration boundary is explicitly chosen: command invocation first, local API only if command invocation is insufficient.
- Any local API option includes a threat model for localhost exposure.
- Documented data flow includes input file handling, output path handling, redacted errors, audit run ID, and sandbox backend configuration.

**Suggested verification command or manual check:**
```bash
test -f docs/tauri_desktop_architecture.md
uv run pytest
```

### Task 38: Add Local JSON Command Interface

**Goal:** Add a machine-readable local command for desktop integration.

**Example command:**
```bash
python -m snapscript run-json \
  --input input.csv \
  --output output.csv \
  --task "Keep only orders where amount is greater than 1000"
```

**Expected JSON shape:**
```json
{
  "success": true,
  "output_path": "...",
  "preview": [],
  "error": null,
  "audit_run_id": "..."
}
```

**Files likely touched:**
- Modify: `src/snapscript/__main__.py`
- Modify: `src/snapscript/interfaces/cli.py` or create `src/snapscript/interfaces/json_command.py`
- Create: `tests/test_json_command_interface.py`

**Dependencies:** Task 37.

**Acceptance criteria:**
- JSON mode has no rich formatting.
- JSON mode returns structured success/failure.
- JSON mode returns a bounded preview, not full output contents.
- JSON mode redacts errors.
- JSON mode still calls `retry_handler.run(...)`.
- JSON mode respects `sandbox_backend` config.
- JSON mode can return an `audit_run_id` when an accepted run writes an audit event.
- JSON mode does not expose raw generated code, prompts, secrets, environment variables, or stack traces by default.
- Normal pytest does not call a real provider.

**Suggested verification command:**
```bash
uv run pytest tests/test_json_command_interface.py tests/test_cli.py
env -u ANTHROPIC_API_KEY uv run pytest
```

### Task 39: Minimal Tauri Shell

**Goal:** Plan and implement a minimal desktop shell.

**UI surface:**
- Select file.
- Enter task.
- Generate.
- Show preview.
- Save output.
- Show redacted errors.

**Files likely touched:**
- Create: reviewed Tauri project files under a dedicated desktop directory.
- Create or modify: `docs/tauri_desktop_architecture.md`
- Create: desktop smoke test or documented manual checklist.

**Dependencies:** Task 38.

**Acceptance criteria:**
- User can double-click the desktop app.
- User can choose `.csv`, `.xlsx`, or `.xls`.
- User can enter a natural-language task.
- App calls the local SnapScript JSON command.
- App does not call provider SDKs directly.
- App does not execute generated code directly.
- Output preview is shown from structured JSON or validated output.
- Output can be saved.
- Redacted errors are shown.
- No dashboard, auth, billing, cloud backend, or multi-user features are added.
- Desktop smoke check is documented.

**Suggested verification command or manual check:**
```bash
uv run pytest tests/test_json_command_interface.py
# Desktop build/test command to be selected after the Tauri project is created.
```

Manual check: select `tests/fixtures/integration/task_02_orders.csv`, enter "Keep only orders where amount is greater than 1000.", generate output, preview rows, and save the result.

## 8. Phase 3C: MCP Server

MCP is a future interface, not a replacement for CLI, Streamlit, or Tauri. It should expose SnapScript capabilities to clients such as Claude, Cursor, Codex, and ChatGPT, while preserving the same safe core pipeline and sandbox backend behavior.

MCP tools must not execute generated code directly. MCP tools must not call provider SDKs directly. When a transform tool is added, it must call the same core flow used by CLI and Streamlit.

Phase 3C should start after Phase 3A. It may run in parallel with late Phase 3B only if the execution backend router is stable and the interface contract is clear.

### Task 40: MCP Server Skeleton

**Goal:** Plan and implement a minimal MCP server.

**Likely files:**
- Create: `src/snapscript/interfaces/mcp_server.py`
- Create: `tests/test_mcp_server.py`
- Create: `docs/mcp_server.md`

**Initial capabilities:**
- `inspect_file_schema` tool.
- `snapscript://version` resource.
- `snapscript://supported-formats` resource.

**Dependencies:** Task 36.

**Acceptance criteria:**
- MCP server starts locally.
- MCP code lives under `src/snapscript/interfaces/`.
- MCP server exposes basic SnapScript metadata.
- MCP server can inspect a local CSV/Excel schema.
- `inspect_file_schema` calls `schema_inspector.inspect(...)`.
- MCP server does not call the provider yet.
- MCP server does not execute generated code yet.
- MCP server does not expose full raw file contents.
- Tests do not require a real MCP client unless explicitly marked.
- Normal pytest remains no-provider.

**Suggested verification command:**
```bash
uv run pytest tests/test_mcp_server.py
env -u ANTHROPIC_API_KEY uv run pytest
```

### Task 41: MCP `transform_file` Tool

**Goal:** Plan and implement a real transform tool.

**Example arguments:**
```json
{
  "input_path": "/path/to/input.csv",
  "task": "Keep only orders where amount is greater than 1000",
  "output_path": "/path/to/output.csv"
}
```

**Files likely touched:**
- Modify: `src/snapscript/interfaces/mcp_server.py`
- Modify: `tests/test_mcp_server.py`
- Modify: `docs/mcp_server.md`

**Dependencies:** Task 40.

**Acceptance criteria:**
- `transform_file` calls `schema_inspector.inspect(...)`, `prompt_builder.build(...)`, and `retry_handler.run(...)`.
- `transform_file` respects `sandbox_backend` config.
- `transform_file` writes one audit event if audit logging is enabled.
- `transform_file` returns structured success/failure.
- `transform_file` returns output metadata and path, not full raw output contents by default.
- `transform_file` never returns raw generated code by default.
- `transform_file` never exposes API keys, prompts, full stack traces, or raw uploaded data.
- Provider calls remain explicit consequences of invoking `transform_file`, not server startup or resource reads.
- Tests mock the provider boundary and do not call a real provider.

**Suggested verification command:**
```bash
uv run pytest tests/test_mcp_server.py tests/test_retry_handler.py
env -u ANTHROPIC_API_KEY uv run pytest
```

## 9. Task 42: Gate - Phase 3A Docker Hardening Complete

**Goal:** Confirm the Docker sandbox hardening path is complete and safe enough for GitHub public release.

**Dependencies:** Tasks 32-36.

**Deferred:** Tasks 37-41 are deferred as future integration work:

- Task 37: Define Desktop App Boundary
- Task 38: Add Local JSON Command Interface
- Task 39: Minimal Tauri Shell
- Task 40: MCP Server Skeleton
- Task 41: MCP `transform_file` Tool

**Acceptance criteria:**

- Full test suite passes.
- Normal pytest does not require Docker.
- Normal pytest does not require provider credentials.
- CLI still works.
- Streamlit still works.
- Core remains interface-agnostic.
- `safety_checker.check(...)` remains mandatory before execution.
- `retry_handler.run(...)` remains the high-level execution path.
- `execution_backend.execute(...)` selects subprocess or Docker based on `AppConfig.sandbox_backend`.
- Subprocess sandbox remains the default backend.
- Docker sandbox is opt-in through config or `SNAPSCRIPT_SANDBOX_BACKEND=docker`.
- Docker sandbox path works when explicitly enabled.
- Subprocess sandbox path remains available unless a later deprecation task is approved.
- Docker image builds successfully.
- Docker command includes runtime restrictions:
  - `--network none` by default
  - memory limit
  - CPU limit
  - PID limit
  - per-run temporary workspace mount only
- Docker command does not mount the repository root.
- Docker command does not mount the user home directory.
- Docker workspace permissions allow the non-root container user to read copied input/script files and write output only inside the per-run temporary workspace.
- No generated code runs directly in CLI or Streamlit.
- Audit logging remains safe and metadata-only by default.
- Raw uploaded datasets, prompts, generated code, API keys, `.env` contents, environment variables, secrets, and full tracebacks are not logged by default.
- No Phase 3A non-goals were added.

**Suggested verification commands:**

```bash
uv run pytest
env -u ANTHROPIC_API_KEY uv run pytest
uv run python main.py --help
SNAPSCRIPT_SANDBOX_BACKEND=subprocess uv run pytest
docker build -t snapscript-sandbox:local docker/sandbox
SNAPSCRIPT_SANDBOX_BACKEND=docker uv run pytest tests/test_docker_sandbox_executor.py tests/test_execution_backend.py tests/test_retry_handler.py
```

**Optional real-provider Docker gate:**

Run only when explicitly validating the real-provider Docker path and when API usage is acceptable:

```bash
SNAPSCRIPT_REAL_PROVIDER=1 SNAPSCRIPT_SANDBOX_BACKEND=docker uv run pytest tests/integration/test_cli_gate_tasks.py
```

**Manual checks:**

- Launch Streamlit and complete the Task 02 fixture flow.
- Run the CLI against the Task 02 fixture with subprocess backend.
- Run the CLI against the Task 02 fixture with Docker backend.
- Confirm Docker image builds successfully.
- Confirm Docker command includes `--network none`, memory limit, CPU limit, and PID limit.
- Confirm Docker mounts only the per-run temporary workspace.
- Confirm audit logs contain metadata and hashes only by default.
- Confirm `.env`, API keys, raw uploaded data, raw prompts, and generated code are not logged by default.
- Confirm Tauri and MCP work is deferred, not partially implemented.

## 10. Recommended Task Order

Implement Phase 3 in this order:

| Task | Title | Priority |
|------|-------|----------|
| Task 32 | Docker Sandbox Executor Skeleton | Required first |
| Task 33 | Sandbox Backend Configuration | Required |
| Task 34 | Minimal Sandbox Docker Image | Required |
| Task 35 | Docker Runtime Restrictions | Required |
| Task 36 | Execution Backend Router | Required |
| Task 37 | Define Desktop App Boundary | After Docker router |
| Task 38 | Add Local JSON Command Interface | After desktop boundary |
| Task 39 | Minimal Tauri Shell | After JSON command |
| Task 40 | MCP Server Skeleton | After Docker router |
| Task 41 | MCP `transform_file` Tool | After MCP skeleton |
| Task 42 | Gate - Phase 3A Docker Hardening Complete | Phase 3A gate |

Do not start Tasks 37-41 until Task 36 is complete unless the work is limited to documentation that does not affect code paths.

## 11. Acceptance Criteria

Phase 3 is accepted when:

- Docker sandbox backend exists and can be explicitly enabled.
- Subprocess backend remains available and tested.
- `execution_backend.execute(...)` selects the configured backend.
- `retry_handler.run(...)` still calls `safety_checker.check(...)` before execution.
- CLI and Streamlit still call the safe high-level core path.
- Normal `uv run pytest` passes without Docker or provider credentials.
- Docker-specific tests pass when Docker is available and explicitly enabled.
- Real-provider Docker CLI gate passes only through explicit opt-in.
- Tauri path has a stable JSON command boundary and does not duplicate core logic.
- MCP server, if implemented, exposes safe tools/resources and uses the same core pipeline.
- Audit logging remains metadata-only by default.
- No interface directly executes generated code.
- No Phase 3 non-goals were added.

## 12. Suggested Verification Commands

Default verification:

```bash
uv run pytest
env -u ANTHROPIC_API_KEY uv run pytest
uv run python main.py --help
```

Subprocess backend verification:

```bash
SNAPSCRIPT_SANDBOX_BACKEND=subprocess uv run pytest
```

Docker backend verification:

```bash
docker build -t snapscript-sandbox:local docker/sandbox
SNAPSCRIPT_SANDBOX_BACKEND=docker uv run pytest tests/test_docker_sandbox_executor.py
SNAPSCRIPT_SANDBOX_BACKEND=docker uv run pytest tests/test_execution_backend.py tests/test_retry_handler.py
```

Explicit real-provider Docker gate:

```bash
SNAPSCRIPT_REAL_PROVIDER=1 SNAPSCRIPT_SANDBOX_BACKEND=docker uv run pytest tests/integration/test_cli_gate_tasks.py
```

Boundary checks:

```bash
uv run python -c "import pathlib; source=''.join(p.read_text() for p in pathlib.Path('src/snapscript/core').glob('*.py')); assert 'streamlit' not in source"
uv run python -c "import pathlib, re; source=pathlib.Path('src/snapscript/interfaces/web.py').read_text(); assert 'Anthropic' not in source and 'sandbox_executor.execute(' not in source"
```

Do not add real-provider Streamlit, Tauri, or MCP checks to default pytest.

## 13. Risks And Mitigations

| Risk | Mitigation |
|------|------------|
| Docker is unavailable on a developer machine or CI worker. | Keep subprocess as default initially; skip Docker tests unless Docker is available or explicitly enabled. |
| Docker command construction becomes brittle or platform-specific. | Unit-test command construction separately from Docker execution; document supported platforms. |
| Container image grows too large. | Start with a minimal runtime image and only install pandas/openpyxl/chardet plus required runtime dependencies. |
| Runtime restrictions break legitimate generated scripts. | Add focused tests for normal pandas CSV/Excel reads/writes before tightening flags further. |
| Docker sandbox is mistaken as replacing static checks. | Keep `safety_checker` before backend routing and test the call order in `retry_handler`. |
| Interfaces start bypassing the core pipeline. | Add tests that CLI, Streamlit, Tauri JSON, and MCP paths call `retry_handler.run(...)` or the approved high-level helper. |
| Error messages leak paths, prompts, code, or secrets. | Reuse redaction helpers and add tests for provider, safety, sandbox, Docker, JSON command, and MCP errors. |
| Audit logs become a hidden data leak. | Keep hashes and metadata by default; require explicit local debug env var for raw prompt/code fields; never log raw datasets. |
| Tauri scope expands into product features. | Keep Task 39 to file selection, task entry, Generate, preview, save output, and redacted errors only. |
| MCP becomes a second product surface before sandbox hardening. | Start MCP after Task 36 and keep the first MCP task metadata/schema-only. |
| Real-provider tests start running by default. | Keep all real-provider gates behind `SNAPSCRIPT_REAL_PROVIDER=1`. |

## 14. What Not To Do

- Do not remove the subprocess backend during Phase 3A.
- Do not make Docker required for normal pytest.
- Do not make provider credentials required for normal pytest.
- Do not run generated code directly from CLI, Streamlit, Tauri, or MCP.
- Do not call provider SDKs directly from any interface layer.
- Do not call `sandbox_executor.execute(...)` or `docker_sandbox_executor.execute(...)` directly from interface layers once the backend router exists.
- Do not weaken `safety_checker`.
- Do not replace `_snapscript_paths.py` with string path injection.
- Do not mount the repo root or user home into the Docker sandbox.
- Do not enable Docker network access by default.
- Do not log raw uploaded datasets, prompts, generated code, API keys, `.env` contents, environment variables, secrets, or full tracebacks by default.
- Do not add MLflow, a database, cloud logging, auth, billing, team workspaces, or dashboards as part of Phase 3.
- Do not rewrite the Python core in Rust for Tauri.
- Do not make MCP a separate execution pipeline.
- Do not add data visualization, multi-file workflows, web scraping, PDF/image processing, or database connectors.
