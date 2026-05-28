# SnapScript

SnapScript is a local AI-assisted CSV/Excel transformation tool that turns natural-language data tasks into sandboxed, validated pandas executions.

It supports both single-file transformations and named two-file workflows such as joins and merges, while keeping generated code behind safety checks, sandbox execution, output validation, and retry handling.

## What SnapScript Does

SnapScript takes a user task plus one or two local CSV/Excel files and runs the task through a defensive AI execution pipeline:

```text
User task + CSV/Excel input(s)
  -> schema inspection
  -> schema-aware prompt construction
  -> LLM-generated pandas code
  -> AST safety check
  -> sandbox backend selection
  -> subprocess or Docker execution
  -> output validation
  -> retry/fallback handling
  -> CLI or Streamlit result
```

Generated code is treated as untrusted. It is never executed directly from the CLI or Streamlit UI.

## Why It Is Interesting

SnapScript is not just a chat wrapper around a spreadsheet. It is designed around a safe local execution architecture:

- Schema-aware prompts help the LLM generate pandas code that matches the uploaded data.
- AST-based validation rejects unsafe imports, unsafe calls, and suspicious literal path access before execution.
- Generated code runs through a selected sandbox backend instead of directly in the interface layer.
- Subprocess and Docker sandbox backends are both supported.
- Docker execution is opt-in and adds container isolation, network denial, memory limits, CPU limits, PID limits, and temporary workspace mounting.
- Output files must be present, non-empty, and readable before they are exposed to the user.
- CLI and Streamlit stay thin; core logic lives under `src/snapscript/core/`.
- Streamlit audit logging stores local metadata and hashes by default, not raw uploaded data, full prompts, or generated code.

## Current Features

- Natural-language CSV/Excel transformations
- Single-file CSV, XLSX, and XLS workflows
- Named two-file input workflows for joins and merges
- CLI support for repeated named `--file` inputs
- Streamlit support for single-file and two-file upload flows
- Schema inspection for CSV/Excel inputs
- Multi-file schema-aware prompt construction
- Anthropic Claude code generation with retry and fallback model support
- AST safety checker for generated Python
- Subprocess sandbox backend
- Docker sandbox backend
- Runtime sandbox backend display in the Streamlit sidebar
- Output validation before copy-out, preview, or download
- Redacted user-facing errors
- Streamlit session rate limiting and cooldowns
- Metadata-only local audit logging for accepted Streamlit Generate runs

## Architecture

```text
CLI / Streamlit
  -> schema_inspector
  -> prompt_builder
  -> retry_handler
      -> code_generator
      -> safety_checker
      -> execution_backend
          -> subprocess sandbox
          -> Docker sandbox
      -> output validation
  -> audit_logger where applicable
```

Core modules live under:

```text
src/snapscript/core/
```

Interface modules live under:

```text
src/snapscript/interfaces/
```

Important boundaries:

- Interface layers do not call provider SDKs directly.
- Interface layers do not execute generated code directly.
- Generated code must pass `safety_checker.check(...)` before sandbox execution.
- `retry_handler.run(...)` remains the high-level safe execution path.
- `execution_backend.execute(...)` selects the configured sandbox backend.
- Real input paths are not injected into generated code.
- `_snapscript_paths.py` provides safe workspace paths through `INPUT_PATH`, `INPUT_PATHS`, and `OUTPUT_PATH`.

## Installation

```bash
git clone https://github.com/ctkuo2438/SnapScript.git
cd SnapScript
uv sync
```

SnapScript is a Python 3.10+ project managed with `uv`.

## Environment Setup

SnapScript currently implements Anthropic Claude as the real LLM provider.

Normal tests do not require provider credentials. Real-provider CLI or Streamlit runs require `ANTHROPIC_API_KEY`.

Option A: export the key in your shell.

```bash
export ANTHROPIC_API_KEY="your_anthropic_api_key_here"
```

Option B: use a local `.env` file.

```bash
cp .env.example .env
# edit .env
set -a
source .env
set +a
```

Do not commit `.env` or real API keys.

## CLI Usage

Show CLI help:

```bash
uv run python main.py --help
```

### Single-file transformation

```bash
uv run python main.py \
  "Keep only orders where amount is greater than 1000." \
  --file tests/fixtures/integration/task_02_orders.csv \
  --output /tmp/orders_over_1000.csv \
  --yes
```

### Two-file join or merge

Phase 4A adds named two-file input support. Use repeated `--file` arguments with logical names:

```bash
uv run python main.py \
  "Merge orders and products using the pid column with an inner join." \
  --file orders=tests/fixtures/integration/orders.csv \
  --file products=tests/fixtures/integration/products.csv \
  --output /tmp/orders_with_products.csv \
  --yes
```

Logical names should be lowercase identifiers such as `orders`, `products`, or `customers_2025`.

## Streamlit Usage

```bash
uv run streamlit run app.py
```

The Streamlit app supports:

- Single-file upload
- Two-file upload with logical input names
- Natural-language task entry
- Generate button as the only transformation trigger
- Output preview
- Download button after successful validation
- Session run limit and cooldown
- Redacted errors
- Local metadata-only audit logging
- Sidebar display of the selected sandbox backend

## Docker Sandbox Usage

The default backend is `subprocess`.

The Docker backend is opt-in:

```bash
docker build -t snapscript-sandbox:local docker/sandbox
export SNAPSCRIPT_SANDBOX_BACKEND=docker
```

Run the CLI with Docker enabled:

```bash
SNAPSCRIPT_SANDBOX_BACKEND=docker uv run python main.py \
  "Keep only orders where amount is greater than 1000." \
  --file tests/fixtures/integration/task_02_orders.csv \
  --output /tmp/orders_over_1000.csv \
  --yes
```

Docker Desktop or Docker Engine must be running.

See `docs/docker_sandbox.md` for image details, runtime restrictions, workspace permissions, and troubleshooting.

## Testing

Normal tests are provider-free and Docker-free by default:

```bash
uv run pytest
env -u ANTHROPIC_API_KEY uv run pytest
uv run python main.py --help
```

Focused Phase 4A checks:

```bash
uv run pytest tests/test_schema_inspector.py tests/test_prompt_builder.py
uv run pytest tests/test_sandbox_executor.py tests/test_docker_sandbox_executor.py tests/test_execution_backend.py tests/test_retry_handler.py
uv run pytest tests/test_cli.py tests/test_streamlit_app.py tests/test_streamlit_pipeline_integration.py
uv run pytest tests/integration/test_multi_file_join.py
```

Docker-focused checks:

```bash
docker build -t snapscript-sandbox:local docker/sandbox
SNAPSCRIPT_SANDBOX_BACKEND=docker uv run pytest tests/test_docker_sandbox_executor.py tests/test_execution_backend.py tests/test_retry_handler.py
```

Real-provider gate:

```bash
SNAPSCRIPT_REAL_PROVIDER=1 uv run pytest tests/integration/test_cli_gate_tasks.py
```

Optional real-provider Docker gate:

```bash
SNAPSCRIPT_REAL_PROVIDER=1 SNAPSCRIPT_SANDBOX_BACKEND=docker uv run pytest tests/integration/test_cli_gate_tasks.py
```

Real-provider gates are opt-in and consume provider API credits.

## Security Model

Generated code is treated as untrusted.

SnapScript applies multiple layers of defense:

- Generated code must pass AST safety validation before execution.
- Unsafe imports, unsafe calls, and unsafe literal path access are rejected.
- Generated scripts use `_snapscript_paths.py` for safe path injection.
- Real user paths are not inserted into generated code.
- Generated code runs through a selected sandbox backend.
- Docker sandbox execution disables network access by default.
- Docker applies memory, CPU, and PID limits.
- Docker mounts only a per-run temporary workspace.
- Docker does not mount the repository root or user home directory.
- Output must exist, be non-empty, and be readable before it is copied out or exposed.
- Streamlit audit logs store metadata and hashes by default.
- Raw uploaded datasets, prompts, generated code, API keys, `.env` contents, environment variables, secrets, and full tracebacks are not logged by default.

SnapScript is a local developer tool. It is not a formal production-grade security boundary for hostile multi-tenant workloads.

## Supported Providers

Currently implemented:

- Anthropic Claude

Possible future adapters:

- OpenAI GPT
- DeepSeek
- OpenAI-compatible APIs

Those future adapters are not implemented today.

## Limitations

- SnapScript is local-first, not a hosted multi-user product.
- Docker backend requires Docker installed, running, and the sandbox image built.
- Phase 4A supports at most two input files.
- Multi-file workflows are named input workflows, not a full relational query planner.
- SnapScript does not parse natural-language joins itself; it provides schema context and safe file abstractions to the LLM.
- Tauri desktop app and MCP server work are deferred.
- No cloud execution, auth, billing, team workspace, dashboard, web scraping, or database connector is included.

## Roadmap

Near-term:

- Phase 4B Prompt Assistant
  - Rule-based Prompt Coach
  - LLM-based task rewrite helper
  - Streamlit task improvement UI

Future:

- Local JSON command interface
- Tauri desktop shell
- MCP server
- Additional provider adapters
- More sandbox hardening, such as read-only root filesystem plus explicit tmpfs mounts
- More file workflows beyond the current two-file Phase 4A limit
