# SnapScript

SnapScript is a local AI-assisted CSV/Excel transformation tool that turns natural-language data tasks into sandboxed, validated pandas executions.

## Overview

SnapScript accepts a user task plus one or two local spreadsheet files, asks the configured LLM provider to generate pandas code, checks the generated code, runs it in a local sandbox backend, validates the output, and returns a CSV or Excel result.

Generated code is treated as untrusted. CLI, Streamlit and MCP reuse the same safe core pipeline.

## Spec-Driven Development

Codex or Claude Code develops this repository from [spec.md](spec.md), guided by
[AGENTS.md](AGENTS.md) and the [development guide](docs/development.md). The agent compares the spec
with current behavior, adds regression tests, makes minimal changes, runs tests,
repairs failures, and reports evidence for each acceptance criterion in
[the verification report](docs/ai_csv_merge_verification.md).

Example development instruction:

> Read AGENTS.md and spec.md. Follow the implementation checklist, reuse the
> existing pipeline, run the verification gates, fix failures, and update the
> acceptance report. Mark unavailable Docker/provider checks as unverified.
> Do not commit or push.

This is the development workflow; SnapScript's runtime remains the existing safe
CSV/Excel pipeline. The AI CSV Merge spec defines default key/join behavior,
input errors, source preservation, and a separate Docker isolation gate.

## Agent Integration

SnapScript provides a local stdio MCP server with two tools:
`inspect_file_schema` and `transform_files`. Start it with an existing data directory:

```bash
mkdir -p data
uv run --env-file .env python -m snapscript.interfaces.mcp_server --workspace ./data
```

Inspection returns column names/types without cell samples. Transformation uses
the configured Claude provider, AST checks and Docker; build the
[sandbox image](docs/docker_sandbox.md#build) first. Both tools accept one or two
named CSV/XLSX inputs inside the workspace; outputs must use a new filename.

See [Agent usage and MCP](docs/development.md#agent-usage-and-mcp) for Claude Code
registration, tool arguments and task-spec workflow, and
[the MCP spec](specs/mcp.md) for acceptance evidence. Agents with terminal access
can also use the CLI.

## Features

- CSV and XLSX input support
- Single-file transformations
- Named two-file workflows such as joins, merges, and combines
- CLI, Streamlit and local MCP interfaces over the same core pipeline
- Prompt Coach for non-blocking task-quality suggestions
- Optional AI Task Rewrite after an explicit user click
- Anthropic Claude provider integration
- Model override for CLI smoke tests with `--model`
- AST safety checking before execution
- Subprocess sandbox backend by default
- Optional Docker sandbox backend for CLI/web; mandatory for MCP transformations
- Output validation before copy-out, preview, or download
- Redacted user-facing errors
- Streamlit run limits, rewrite limits, and cooldowns
- Metadata-only local audit logging for accepted Streamlit Generate and AI Rewrite attempts

## Safety Model

SnapScript uses a layered local safety model:

```text
file(s) + task
  -> schema inspection
  -> prompt building
  -> code generation
  -> AST safety checking
  -> execution backend router
  -> subprocess or Docker sandbox
  -> output validation
  -> retry handling
```

Important boundaries:

- Generated code must pass `safety_checker.check(...)` before sandbox execution.
- Docker sandboxing does not replace AST safety checking.
- The execution backend is the only route to subprocess or Docker execution.
- Real user paths are not inserted into prompts or generated code.
- `_snapscript_paths.py` provides safe workspace paths through `INPUT_PATH`, `INPUT_PATHS`, and `OUTPUT_PATH`.
- Output files must exist, be non-empty, and be readable before they are exposed.
- Audit logs store metadata and hashes by default, not raw uploaded data, full prompts, or generated code.

SnapScript is a local developer tool. It is not a production-grade security boundary for hostile multi-tenant workloads.

## Installation

```bash
git clone https://github.com/ctkuo2438/SnapScript.git
cd SnapScript
uv sync
```

SnapScript requires Python 3.10+ and uses `uv` for dependency management.

## Configuration

SnapScript currently implements Anthropic Claude as the real LLM provider. Normal tests do not require provider credentials. Real CLI, Streamlit and MCP transformations require an Anthropic API key.

Create a local environment file from the example:

```bash
cp .env.example .env
```

To load that file, start commands with `uv run --env-file .env`, for example
`uv run --env-file .env streamlit run app.py`.

Or export the key directly:

```bash
export ANTHROPIC_API_KEY="your_anthropic_api_key_here"
```

Do not commit `.env` or real API keys.

Common environment variables:

| Variable | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Anthropic provider key for real generation/rewrite calls |
| `SNAPSCRIPT_SANDBOX_BACKEND` | Sandbox backend: `subprocess` or `docker` |
| `SNAPSCRIPT_DOCKER_IMAGE` | Docker sandbox image name, default `snapscript-sandbox:local` |
| `SNAPSCRIPT_DOCKER_TIMEOUT_SECONDS` | Docker execution timeout |
| `SNAPSCRIPT_DOCKER_MEMORY_LIMIT` | Docker memory limit |
| `SNAPSCRIPT_DOCKER_CPU_LIMIT` | Docker CPU limit |
| `SNAPSCRIPT_DOCKER_NETWORK_DISABLED` | Disable Docker container networking, default `true` |
| `SNAPSCRIPT_REAL_PROVIDER` | Opt-in flag for real-provider integration tests |
| `SNAPSCRIPT_AUDIT_INCLUDE_PROMPTS` | Local debug-only audit option for redacted task/prompt fields |

## CLI Usage

Show CLI help:

```bash
uv run python main.py --help
```

Single-file mode:

```bash
uv run python main.py \
  "Keep only orders where amount is greater than 1000." \
  --file tests/fixtures/integration/task_02_orders.csv \
  --output /tmp/orders_over_1000.csv \
  --yes
```

Two-file mode uses repeated named `--file NAME=PATH` arguments:

```bash
uv run python main.py \
  "Merge orders and products using the pid column with an inner join." \
  --file orders=orders.csv \
  --file products=products.csv \
  --output /tmp/orders_with_products.csv \
  --yes
```

Logical names should be lowercase identifiers such as `orders`, `products`, or `customers_2025`.

Dry-run and show generated code after safety checking:

```bash
uv run python main.py \
  "Keep only orders where amount is greater than 1000." \
  --file tests/fixtures/integration/task_02_orders.csv \
  --output /tmp/orders_over_1000.csv \
  --dry-run \
  --show-code
```

Use a specific model for one CLI run:

```bash
uv run python main.py \
  "Keep only orders where amount is greater than 1000." \
  --file tests/fixtures/integration/task_02_orders.csv \
  --output /tmp/orders_over_1000.csv \
  --model claude-opus-4-20250514 \
  --yes
```

## Streamlit App

Run the local web UI:

```bash
uv run streamlit run app.py
```

The Streamlit app supports:

- Single-file upload
- Two-file upload with logical input names
- Prompt Coach suggestions
- Explicit AI Task Rewrite
- Generate as the only action that runs the transformation pipeline
- Output preview and download after successful validation
- Sidebar display of the active sandbox backend
- Local metadata-only audit logging

## Sandbox Backends

The default backend is `subprocess`.

The Docker backend is optional:

```bash
docker build -t snapscript-sandbox:local docker/sandbox
SNAPSCRIPT_SANDBOX_BACKEND=docker uv run streamlit run app.py
```

CLI with Docker backend:

```bash
SNAPSCRIPT_SANDBOX_BACKEND=docker uv run python main.py \
  "Keep only orders where amount is greater than 1000." \
  --file tests/fixtures/integration/task_02_orders.csv \
  --output /tmp/orders_over_1000.csv \
  --yes
```

Docker Desktop or Docker Engine must be running. See `docs/docker_sandbox.md` for image details, runtime restrictions, workspace permissions, and troubleshooting.

## Testing

Normal tests are provider-free and Docker-free by default:

```bash
uv run pytest
env -u ANTHROPIC_API_KEY uv run pytest
```

Focused checks:

```bash
uv run pytest tests/test_streamlit_*.py
uv run pytest tests/test_task_advisor.py tests/test_task_rewriter.py
uv run pytest tests/integration/test_csv_merge_spec.py tests/test_mcp_server.py
```

Optional Docker verification:

```bash
docker build -t snapscript-sandbox:local docker/sandbox
SNAPSCRIPT_DOCKER_TESTS=1 uv run pytest tests/integration/test_csv_merge_docker.py tests/integration/test_mcp_pipeline.py
```

Optional real-provider verification:

```bash
SNAPSCRIPT_REAL_PROVIDER=1 uv run pytest tests/integration/test_cli_gate_tasks.py
```

Real-provider tests are opt-in and consume provider API credits.

## Audit Logging

Streamlit writes local JSONL audit events for accepted Generate and AI Rewrite attempts. The default log path is:

```text
logs/snapscript_audit.jsonl
```

Default audit events store metadata and hashes. Raw uploaded datasets, full prompts, generated code, API keys, `.env` contents, environment variables, secrets, and full tracebacks are not logged by default.

`SNAPSCRIPT_AUDIT_INCLUDE_PROMPTS=1` is a local debugging option that can include redacted task/prompt fields. Leave it unset for normal use.

## Development Notes

The consolidated [development guide](docs/development.md) contains the Phase 1–4
roadmap, architecture, shared gates, and remaining work.

Useful commands:

```bash
uv sync
uv run python main.py --help
uv run streamlit run app.py
uv run pytest
```

Project layout:

```text
src/snapscript/core/        interface-agnostic pipeline modules
src/snapscript/interfaces/  CLI and Streamlit layers
src/snapscript/prompts/     provider prompts
tests/                      unit and integration tests
docs/                       design and verification notes
docker/                     optional Docker sandbox image
```

## Limitations

- Only Anthropic Claude is implemented as a real provider today.
- Two-file mode is limited to two named input files.
- SnapScript does not implement a general relational query planner.
- SnapScript does not parse natural-language joins into custom business logic; the LLM interprets the task.
- Docker backend is optional and requires Docker to be installed and running.
- No cloud execution, auth, billing, hosted team workspace, dashboards, web scraping, or database connectors are included.
- The project is local-first and intended for developer-controlled environments.
