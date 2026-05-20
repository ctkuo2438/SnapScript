# SnapScript

SnapScript is a local AI-assisted CSV/Excel transformation tool that converts natural-language data tasks into sandboxed, validated pandas executions.

## What It Does

SnapScript takes a user task and a local CSV or Excel file, inspects the file schema, asks an LLM to generate pandas code, safety-checks that code, executes it in a selected sandbox backend, validates the output, and returns the result through either the CLI or Streamlit UI.

```text
User task + CSV/Excel file
  -> schema inspection
  -> schema-aware prompt
  -> LLM-generated pandas code
  -> AST safety check
  -> sandbox execution
  -> output validation
  -> retry/fallback handling
  -> Streamlit/CLI result
```

## Why It Is Interesting

SnapScript is not just a chat wrapper around a data file. It treats generated code as untrusted and routes it through a defensive execution pipeline:

- AST-based safety checks reject unsafe imports, calls, and literal path access before execution.
- Subprocess and Docker sandbox backends keep generated code behind a core execution boundary.
- Output is validated before being copied out to the requested path.
- UI layers stay thin while `src/snapscript/core/` owns schema, prompt, retry, safety, sandbox, and validation behavior.
- Streamlit audit logging stores metadata and hashes by default, not raw uploaded data, prompts, or generated code.

## Features

- Natural-language CSV/Excel transformations
- CSV, XLSX, and XLS support where implemented by the current pandas/openpyxl/xlrd stack
- Schema inspection and schema-aware prompt construction
- Anthropic Claude code generation with retry and fallback model logic
- AST safety checker for generated Python
- Subprocess sandbox backend
- Docker sandbox backend
- Output validation for missing, empty, or unreadable results
- CLI interface
- Streamlit interface
- Safe audit logging with metadata and hashes by default

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
  -> audit_logger
```

Core modules live under `src/snapscript/core`. Interface code lives under `src/snapscript/interfaces`.

Generated code never runs directly from the CLI or Streamlit UI. `retry_handler.run(...)` remains the high-level safe execution path, and `execution_backend.execute(...)` selects the subprocess or Docker sandbox based on `AppConfig.sandbox_backend`.

## Installation

```bash
git clone https://github.com/ctkuo2438/SnapScript.git
cd SnapScript
uv sync
```

SnapScript is a Python 3.10+ project managed with `uv`.

## Environment Setup

SnapScript currently implements Anthropic Claude as the real provider. Normal tests do not require a provider API key.

Option A: export the key in your shell.

```bash
export ANTHROPIC_API_KEY="your_anthropic_api_key_here"
```

Option B: create a local `.env` file, edit it, and load it into your shell before running provider-backed commands.

```bash
cp .env.example .env
# edit .env
set -a
source .env
set +a
```

Do not commit `.env` or real API keys. Real-provider tests are opt-in and consume provider API credits.

## CLI Usage

Show CLI options:

```bash
uv run python main.py --help
```

Run with the default subprocess backend:

```bash
uv run python main.py \
  "Keep only orders where amount is greater than 1000." \
  --file tests/fixtures/integration/task_02_orders.csv \
  --output /tmp/orders_over_1000.csv \
  --yes
```

Run with the Docker backend:

```bash
docker build -t snapscript-sandbox:local docker/sandbox

SNAPSCRIPT_SANDBOX_BACKEND=docker uv run python main.py \
  "Keep only orders where amount is greater than 1000." \
  --file tests/fixtures/integration/task_02_orders.csv \
  --output /tmp/orders_over_1000.csv \
  --yes
```

## Streamlit Usage

```bash
uv run streamlit run src/snapscript/interfaces/web.py
```

The Streamlit interface supports local upload, task entry, output preview, download, rate limiting, redacted errors, and metadata-only audit logging.

## Docker Sandbox Usage

The Docker backend is opt-in. The default backend remains `subprocess`.

Build the sandbox image:

```bash
docker build -t snapscript-sandbox:local docker/sandbox
```

Opt in for a shell session:

```bash
export SNAPSCRIPT_SANDBOX_BACKEND=docker
```

Docker Desktop or Docker Engine must be running. See [docs/docker_sandbox.md](docs/docker_sandbox.md) for runtime restrictions, workspace permissions, and troubleshooting.

## Testing

Normal test runs are provider-free and Docker-free by default:

```bash
uv run pytest
env -u ANTHROPIC_API_KEY uv run pytest
uv run python main.py --help
SNAPSCRIPT_SANDBOX_BACKEND=subprocess uv run pytest
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

Real-provider gates are opt-in and consume Anthropic API credits.

## Security Model

Generated code is treated as untrusted.

- Generated code must pass `safety_checker.check(...)` before execution.
- Generated code runs through the selected sandbox backend.
- The Docker backend adds container runtime isolation.
- Docker disables network access by default with `--network none`.
- Docker applies memory, CPU, and PID limits.
- Docker mounts only a per-run temporary workspace.
- Workspace permissions are prepared only inside that per-run temporary workspace so the non-root container user can read copied inputs/scripts and write output.
- Output must exist, be non-empty, and be readable before it is copied out.
- Streamlit audit logging stores metadata and hashes by default.
- Raw datasets, prompts, generated code, API keys, `.env` contents, environment variables, secrets, and full tracebacks are not logged by default.

This is a local developer tool, not a formal security boundary for hostile multi-tenant workloads.

## Supported Providers

Currently implemented:

- Anthropic Claude

Possible future adapters:

- OpenAI GPT
- DeepSeek
- OpenAI-compatible APIs

Those future adapters are not implemented today.

## Limitations

- SnapScript is local-first, not a hosted multi-user app.
- Docker backend use requires Docker installed, running, and the sandbox image built.
- Generated code execution is constrained, but this is not a replacement for a production multi-tenant isolation system.
- No public hosted demo is included.
- Tauri desktop app and MCP server work are deferred.
- No cloud execution, auth, billing, team workspace, dashboard, web scraping, database connector, or multi-file pipeline support is included.

## Roadmap / Future Work

- Local JSON command interface
- Tauri desktop shell
- MCP server
- Additional provider adapters
- More sandbox hardening, such as a read-only root filesystem with explicit tmpfs mounts after smoke tests
- More file workflows
