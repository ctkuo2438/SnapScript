# AI CSV Merge verification

Verified on 2026-10-10 against [spec.md](../spec.md).

The initial implementation passed all defined verification gates. The feature uses the existing Python
pipeline, CLI, Streamlit UI, Anthropic SDK, and Docker image. Codex/Claude Code
develop from the spec using the shared workflow in [AGENTS.md](../AGENTS.md) and
[CLAUDE.md](../CLAUDE.md).

## Implementation

- Added a concrete spec with merge decisions, independent expected CSV values,
  a completed implementation checklist, AC IDs, and separate external gates.
- Added merge guidance to the multi-file prompt: default inner join, sole-common
  key inference, exact explicit keys, full-data key validation, and duplicate
  pairings. Input errors and empty results do not trigger generation retries.
- Enforced the two-input limit in core validation and both execution backends.
- Shared destination/output validation between backends. Source aliases
  (including symlinks and hardlinks), symlink outputs, and non-file outputs are
  rejected; outputs must be readable and contain a data row.
- Hardened Docker execution with mandatory disabled networking, a maximum
  30-second timeout per attempt, unique container names, and force-removal on
  timeout. Cleanup has a separate 5-second limit and reports failure explicitly.

No new dependencies were added. Existing single-file path variables, AST checks,
backend routing, and interface behavior were preserved. Existing uncommitted
changes were retained; this work was not committed or pushed.

## Command results

The pre-change credential-free suite passed with **440 tests**. Final results:

| Command | Result |
| --- | --- |
| `uv run pytest` | 474 passed, 8 skipped; 8.79 seconds |
| `env -u ANTHROPIC_API_KEY uv run pytest` | 474 passed, 8 skipped; 9.63 seconds |
| `env -u ANTHROPIC_API_KEY uv run pytest tests/test_prompt_builder.py tests/integration/test_csv_merge_spec.py` | 26 passed; 2.87 seconds |
| `env -u ANTHROPIC_API_KEY SNAPSCRIPT_DOCKER_TESTS=1 uv run pytest tests/integration/test_csv_merge_docker.py` | 4 passed; 11.44 seconds |
| `SNAPSCRIPT_REAL_PROVIDER=1 uv run pytest tests/integration/test_csv_merge_real_provider.py` | 4 passed; 28.40 seconds |

The eight normal-suite skips are the four Docker and four real-provider cases.
They passed separately under their explicit opt-in flags. Normal pytest does not
call Claude or require Docker. The provider gate loaded the configured key from
the local `.env` without recording its contents.

Real-provider verification used the configured Anthropic model `claude-sonnet-5`
with generation retries disabled. Docker verification used the existing
`snapscript-sandbox:local` image and Docker daemon 27.5.1.

## Acceptance evidence

| AC | Result | Evidence |
| --- | --- | --- |
| AC1 | Passed | [Schema tests](../tests/test_schema_inspector.py), [prompt tests](../tests/test_prompt_builder.py), and [merge integration](../tests/integration/test_csv_merge_spec.py) cover named inputs/schemas, safe path variables, and rejection of a third input. Direct executor guards are covered by [source tests](../tests/test_source_preservation.py). |
| AC2 | Passed | Deterministic integration compares every output value and column for default/inner/left joins and all four many-to-many pairings. [Real Claude](../tests/integration/test_csv_merge_real_provider.py) and [real Docker](../tests/integration/test_csv_merge_docker.py) independently compare complete inner/left fixture outputs. |
| AC3 | Passed | Deterministic integration covers missing/no/ambiguous keys, null keys, dtype mismatch, and empty results, with one generation call. Real Claude covers missing/ambiguous keys, including the logical input and missing/available column names. Real Docker also executes the missing-key failure. |
| AC4 | Passed | [AST tests](../tests/test_safety_checker.py) and unsafe-code integration assert rejection before the backend starts. |
| AC5 | Passed | Source tests compare bytes after copied-input writes on success/failure/timeout for both backends and reject destination aliases/output symlinks. Real Docker verifies source bytes on success, input error, and a timed-out script that overwrites workspace copies. |
| AC6 | Passed | [Docker unit tests](../tests/test_docker_sandbox_executor.py) check the 30-second cap, cleanup command, and bounded cleanup failure. Actual container inspection confirms network `none`, exactly the workspace bind, 512 MiB memory, 1 CPU, 128 PIDs, a non-root user, and no provider key. The timeout test probes a host-only file outside the mount, checks cleanup precedes workspace deletion, then confirms the container no longer exists. |
| AC7 | Passed | Both complete suites pass. Existing single-file CLI, Streamlit, multi-file, provider-wrapper, safety, and router tests remain green. External gates remain opt-in. |

## Failure repaired during verification

The first real-Claude run passed three of four cases. For a task explicitly
requesting `pid`, Claude substituted `products.sku` when `products.pid` was
missing and returned a successful CSV. This violated the spec.

The prompt now states that a named shared key must exist verbatim in both inputs;
different key names require an explicit per-input request. It also gives the
`pid`/`sku` case as a prohibited inference. Missing/ambiguous cases passed the
focused re-run, and all four real-provider cases passed the final run. The
missing-key assertion checks the input and available column names as well.

## Scope of the evidence

The Claude gate tests four representative tasks through the subprocess backend;
the Docker gate uses a mocked provider and actual containers. They independently
verify model behavior and sandbox behavior. They do not constitute a combined
real-Claude-in-Docker run. Null/type/duplicate/empty edge cases are covered with
deterministic generated scripts, not additional real-provider requests.

Merge intent remains interpreted by the LLM; these tests are regression evidence,
not a guarantee that every future generated program follows the policy. AST and
sandbox checks remain mandatory for every execution. For host isolation, select
`SNAPSCRIPT_SANDBOX_BACKEND=docker`; the subprocess default remains the
compatibility backend. Each Docker attempt is capped at 30 seconds, excluding
provider calls and input preparation; timeouts are not retried.

## Simplification regression gate — 2026-10-10

Removed the rewrite column-guessing rules while retaining empty/code/path checks;
requested new output columns remain valid. UI errors now use the audit redactor,
including colon-separated secrets. Streamlit shares its upload and execution
flows and writes one audit event per accepted Generate; `main()` is 12 lines.
Unused generated-code hashes, debug code, and attempt counts were removed.
Two-file events leave single-file size/hash unset instead of hashing empty bytes.

| Command | Result |
| --- | --- |
| `uv run pytest -q` | 491 passed, 8 skipped |
| `uv run env -u ANTHROPIC_API_KEY pytest -q` | 491 passed, 8 skipped |
| `uv run pytest tests/test_streamlit_app.py -q` | 2 passed |
| `uv run python main.py --help` | Passed |
| `git diff --check` | Passed |

[AppTest](../tests/test_streamlit_app.py) exercises actual Streamlit upload and
Generate controls, the real AST/subprocess pipeline, preview, and download for
single/two-file cases, comparing complete CSV values. Only generation is mocked.
Audit tests also cover execution failure, provider exceptions, missing output,
and unreadable previews. The eight external cases remain opt-in; real Claude and
Docker were not re-run for this cleanup. Their earlier results are recorded above.
