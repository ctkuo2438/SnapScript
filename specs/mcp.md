# Feature: SnapScript MCP

Status: implemented and verified on 2026-10-10. User-authorized local MCP adapter over the existing core;
single-file CLI and Streamlit behavior stay compatible.

## Requirements and decisions

- Use the official Python MCP SDK and local stdio transport. Expose exactly
  `inspect_file_schema` and `transform_files`; no HTTP server or runtime planner.
- Start with `python -m snapscript.interfaces.mcp_server --workspace /data`.
  The workspace must be an existing directory. Paths are relative to that
  directory or absolute paths contained in it, including resolved symlinks.
  Reject paths containing `..` and symlink output destinations.
- Both tools accept `files: dict[str, str]`: one or two logical names mapped to
  CSV/XLSX paths. Reuse core logical-name, format, size, and schema validation.
  XLSX uses the first sheet. No upload protocol or arbitrary Python input.
- `inspect_file_schema(files)` returns named filename/type/size/row-count,
  encoding, sheet names, and column names/dtypes. No cell values or sample rows;
  dtypes are inferred from the existing bounded sample, not the complete file.
  Return at most 100 columns plus total count and an explicit truncation flag.
- `transform_files(files, task, output_path)` inspects and builds the prompt,
  then calls the existing retry pipeline. Use named `INPUT_PATHS` even for one
  input through this new interface; existing single-file interfaces keep
  `INPUT_PATH`. The LLM interprets the task; do not parse join instructions.
- Require a nonempty task, a new CSV/XLSX output path in the workspace, and an
  existing output parent directory. Validate these before calling the provider.
- Force Docker with networking disabled; retain core AST checks, limits,
  source copies, output validation, and timeout/container cleanup. No subprocess
  fallback. Each execution attempt is capped at 30 seconds; provider calls and
  bounded retries are outside that per-attempt execution limit.
- Return structured success/output-path/file-size/execution-time metadata.
  Failures use MCP `isError` with a bounded, secret-redacted useful message.
  Do not return stdout, generated code, prompt, dataset previews, or full traceback.
- Load credentials through the server environment (`uv run --env-file .env`),
  never through tool arguments or into Docker. Inspection needs no credentials
  or Docker. Transformation requires both the provider and Docker.
- The external Agent reads a data-task spec and checks the output against it;
  Markdown parsing, planning, and final acceptance are client responsibilities.

## Acceptance criteria

| ID | Criterion | Verification |
| --- | --- | --- |
| MCP1 | Real stdio discovery exposes exactly the two tools with structured arguments/results | SDK client subprocess test; no provider/Docker |
| MCP2 | CSV/XLSX inspection returns named schema metadata without cell samples or provider calls | Fixture assertions, including known secret cell values |
| MCP3 | One/two-file transformations use the existing pipeline and Docker config | Mocked provider/executor; complete expected CSV values and unchanged source bytes |
| MCP4 | Missing/unsupported files, invalid names/counts, empty task, outside/traversal/symlink paths, existing outputs fail before generation | Parameterized input/output boundary tests |
| MCP5 | Unsafe generated Python is blocked; execution/input errors are useful, redacted, and do not return an output | Real AST with mocked provider/executor; protocol error assertions |
| MCP6 | Ordinary pytest needs neither keys nor Docker; CLI/web regressions pass | Focused tests, full gate, credential-free gate |

Real Docker/provider checks remain explicit opt-in. Report what was actually
executed separately from mocked pipeline verification.

## Implementation checklist

- [x] Record the minimal MCP contract and acceptance criteria before coding.
- [x] Add the SDK, thin stdio adapter, and focused regression tests.
- [x] Verify actual MCP discovery/calls over stdio and core pipeline behavior.
- [x] Update README/development guide with startup, registration, tool arguments,
  Agent task-spec workflow, and actual acceptance evidence.
- [x] Run the full and credential-free test gates; record results below.

## Verification results

Executed on macOS, Python 3.10.18, MCP SDK 2.3.0 and Docker 27.5.1:

| Command | Actual result |
| --- | --- |
| `uv run pytest tests/test_mcp_server.py -q` | 36 passed in 4.30s |
| `uv run pytest` | 527 passed, 10 skipped in 14.66s |
| `env -u ANTHROPIC_API_KEY uv run pytest` | 527 passed, 10 skipped in 13.40s |
| `env SNAPSCRIPT_DOCKER_TESTS=1 SNAPSCRIPT_REAL_PROVIDER=1 uv run --env-file .env pytest tests/integration/test_mcp_pipeline.py tests/integration/test_csv_merge_docker.py -q` | 6 passed in 20.01s |
| `uv run python -m snapscript.interfaces.mcp_server --help` / `uv run python main.py --help` | Both exit 0 |
| `git diff --check` / local Markdown link checks | Passed |

- MCP1–MCP2: actual stdio subprocess discovery and inspection pass with both
  SDK auto and legacy protocol modes. CSV/XLSX metadata has no sample cells;
  101-column input reports the 100-column limit explicitly.
- MCP3: deterministic one/two-file tests compare complete CSV results and
  source bytes; a multi-sheet XLSX test checks the first-sheet transformation,
  XLSX output and unchanged source bytes. These tests replace Docker with the
  real subprocess executor and mock only provider generation/backend selection.
- MCP4–MCP5: invalid paths/files/names/counts/size/tasks/output destinations
  stop before generation; real AST rejection stops before execution. Missing
  columns preserve input/column context; traceback and secret-redaction tests
  pass. Failed calls expose no structured output path.
- MCP6: both complete test gates pass without requiring external services.
  The 10 normal skips are the explicit Docker/provider gates, not failures.
- External evidence: the 6 opt-in passes comprise one MCP call with mocked
  generation and real Docker, one **real stdio → Claude → AST → Docker → CSV**
  call, and the 4 existing Docker merge/isolation/timeout-cleanup regressions.
  Both MCP integrations compare the complete expected inner merge and confirm
  unchanged sources. Client protocol tests use the official SDK; interactive
  Claude Code registration was documented, not performed on the user's account.

No core modules, provider implementation, or CLI/web runtime behavior were
changed for this adapter. The Docker availability fixture is shared between
the existing and new opt-in integration tests.
