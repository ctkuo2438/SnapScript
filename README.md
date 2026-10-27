# SnapScript

Process one or two CSV/XLSX files with natural-language instructions through the
CLI, Streamlit, or MCP tools in Claude Code and Codex. Generated pandas code passes
AST safety checks, sandbox execution, and output validation.

## Set up with AI assistance

Open this repository in your local Claude Code or Codex client and ask:

> Set up SnapScript as a local MCP server for this client using the manual steps
> below. Check prerequisites, install dependencies, and register the server. Guide
> me through API-key entry locally; never ask me to paste it into chat. Verify the
> connection with inspect_file_schema without paid API calls. Do not change
> application code.

The client can help run the setup commands. You still need your own Anthropic API
key for transformations and Docker installed and running for MCP transformations.

## Manual installation

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Commands below use a macOS/Linux shell.

```bash
git clone https://github.com/ctkuo2438/SnapScript.git
cd SnapScript
uv sync --locked
cp .env.example .env
mkdir -p data
```

Edit `.env` and set `ANTHROPIC_API_KEY` to your own key. SnapScript calls the Claude
API even when the outer client is Codex. Keep `.env` local; never commit real keys.
Credentials are read from the environment; the CLI does not accept `--api-key`.
Put your input files in `data/`.

For MCP transformations and the Streamlit UI, start Docker Desktop or Docker
Engine and build the sandbox image once:

```bash
docker build -t snapscript-sandbox:local docker/sandbox
```

Schema inspection needs neither an API key nor Docker. You can skip the Docker
setup when using only the CLI, whose default backend is `subprocess`.

## Connect Claude Code or Codex

After manual installation, run these commands from the repository root in the
same terminal session:

```bash
SNAPSCRIPT_DIR="$(pwd)"
SNAPSCRIPT_UV="$(command -v uv)"
```

Choose your client, or register both.

### Claude Code

```bash
claude mcp add --transport stdio --scope user snapscript -- \
  "$SNAPSCRIPT_UV" --directory "$SNAPSCRIPT_DIR" \
  run --env-file "$SNAPSCRIPT_DIR/.env" \
  python -m snapscript.interfaces.mcp_server \
  --workspace "$SNAPSCRIPT_DIR/data"

claude mcp list
```

### Codex

```bash
codex mcp add snapscript -- \
  "$SNAPSCRIPT_UV" --directory "$SNAPSCRIPT_DIR" \
  run --env-file "$SNAPSCRIPT_DIR/.env" \
  python -m snapscript.interfaces.mcp_server \
  --workspace "$SNAPSCRIPT_DIR/data"

codex mcp list
```

Open a new client session and use `/mcp` to check the connection. The client starts
the server automatically; no separate server terminal is needed. With
`orders.csv` and `products.csv` in `data/`, ask:

> Use SnapScript's inspect_file_schema to inspect orders.csv and products.csv.
> Then use transform_files to inner-join them on pid and save merged.csv.

Both tools accept one or two named CSV/XLSX files within the configured workspace.
Use a new output filename each time; existing outputs are not overwritten.
`files` maps logical names to workspace-relative paths. `transform_files` also
requires `task` and `output_path`. See the [Claude Code](https://code.claude.com/docs/en/mcp) /
[Codex](https://developers.openai.com/codex/mcp) docs for client configuration.

## CLI usage

After manual installation, run a single-file task:

```bash
uv run --env-file .env python main.py \
  "Keep only orders where amount is greater than 1000." \
  --file data/orders.csv --output data/filtered.csv --yes
```

For two files, repeat `--file NAME=PATH` with lowercase logical names:

```bash
uv run --env-file .env python main.py \
  "Merge orders and products on pid with an inner join." \
  --file orders=data/orders.csv \
  --file products=data/products.csv \
  --output data/merged.csv --yes
```

Run `uv run python main.py --help` for options such as `--dry-run`, `--show-code`,
and `--model`. Dry-run still calls the provider but does not execute generated code.

## Streamlit UI

```bash
uv run --env-file .env streamlit run app.py
```

Upload one or two files, describe the task, click Generate, and download the
validated result. Prompt suggestions and optional AI Task Rewrite are also available.

Streamlit runs generated code in Docker by default, so the sandbox image above must
exist; if Docker is unavailable, Generate fails without calling the provider and does
not fall back to `subprocess`. To opt in to `subprocess` anyway, set
`SNAPSCRIPT_SANDBOX_BACKEND=subprocess`; the sidebar then shows a warning because
generated code can reach this computer's files and network.

## Sandbox and limits

- The CLI defaults to `subprocess`. To use Docker, build the image above and
  set `SNAPSCRIPT_SANDBOX_BACKEND=docker` in `.env`.
  Subprocess strips inherited credentials; host-file isolation requires Docker.
- Streamlit defaults to Docker; `SNAPSCRIPT_SANDBOX_BACKEND=subprocess` is an explicit
  opt-in and shows a warning.
- MCP transformations always use Docker with networking disabled and no subprocess
  fallback. Only the per-run temporary workspace is mounted.
- Docker uses a private workspace, restricted privileges and a read-only root
  filesystem. Local UID/GID mapping requires macOS or Linux (including WSL).
- Docker explicitly applies its built-in seccomp profile and verifies filtering
  before calling the provider. Docker execution timeouts must be 1–30 seconds.
- Only CSV and XLSX are supported, with at most two inputs. Outputs must be readable
  and contain data rows. Output files are private (0600); audit logs use metadata
  and hashes by default.

## Development

```bash
uv run pytest
```

Normal tests need neither provider credentials nor Docker. External verification
is opt-in. [AGENTS.md](AGENTS.md) / [CLAUDE.md](CLAUDE.md) contain instructions for
coding agents maintaining the repository; they are not required to run SnapScript.

Keep `uv.lock` in version control so installations use the same resolved dependency
versions. Local environments (`.venv/`), credentials (`.env`), and user datasets are
excluded by `.gitignore`. Development notes, specifications and reports in `docs/`
and `specs/` stay local.
