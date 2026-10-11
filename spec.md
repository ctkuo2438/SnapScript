# Feature: AI CSV Merge

Status: implemented; verification is recorded in
[docs/ai_csv_merge_verification.md](docs/ai_csv_merge_verification.md).
Scope: Phase 4A, at most two named CSV/Excel
inputs; CSV merge is the acceptance example. Preserve existing single-file
CLI, Streamlit, and execution-backend routing.

## Development workflow

Codex or Claude Code is the **development agent**. Read this spec and
`AGENTS.md` and [the development guide](docs/development.md), compare requirements
with existing code, make the smallest necessary
changes, run tests, fix failures, and record evidence in
`docs/ai_csv_merge_verification.md`. SnapScript remains a data-processing tool.
No runtime agent framework, HTTP server, new dependencies, or autonomous
multi-step planner is required.

## Requirements

- Accept two named inputs, such as `orders=orders.csv` and
  `products=products.csv`, plus a natural-language task.
- Inspect column names, sampled data types, and bounded sample rows for each
  named file. Sampling does not guarantee the full file has one data type.
- Use the configured Anthropic SDK/model to generate pandas code. The LLM
  interprets the task; SnapScript must not parse natural-language join keywords.
- Generated multi-file code uses `INPUT_PATHS` and `OUTPUT_PATH` from
  `_snapscript_paths.py`. Never expose real source paths in prompts/code.
- Run AST safety checks before execution. Validate the resulting CSV before
  returning it through the existing CLI or Streamlit download flow.

## Merge decisions

These instructions apply when the user asks for a merge, not to unrelated
two-file transformations. The generated script must validate full input data.

| Situation | Required behavior |
| --- | --- |
| Task names a key | Use that key; do not silently choose a replacement. Explicit differently named or composite keys may follow the task. |
| No key specified | Use the sole common column name. Zero or multiple common columns is a clear error asking the user to specify a key. |
| No join type specified | Use an inner join. Explicit join instructions take precedence. |
| Duplicate keys | Keep every pandas merge pairing, including many-to-many results; do not deduplicate implicitly. |
| Null key values | Reject; identify the logical input name and key. |
| Key dtypes differ | Reject; identify the logical input names/key and ask the user to align types. Do not silently coerce. |
| Missing key/required column | Reject; name the logical input, missing column, and available columns. |
| No result rows | Fail with `Output is empty`; never offer a header-only CSV as success. |
| Overlapping non-key columns | Keep pandas' default `_x`/`_y` suffixes unless the task requests different names. |

Use `ValueError("Input validation: ...")` for known input/key errors so the
pipeline can return a useful error without spending additional generation
attempts. Other execution errors retain the existing bounded retry behavior.
Do not retry safety failures or timeouts.

## Sandbox and source-file constraints

- Hardened acceptance runs explicitly select the existing Docker backend with
  `SNAPSCRIPT_SANDBOX_BACKEND=docker`. Docker failures never fall back to
  subprocess. The existing subprocess default remains available for backward
  compatibility and deterministic local tests; it does not satisfy the Docker
  isolation acceptance gate.
- Docker networking must be disabled; reject a request to enable it.
- Cap each Docker execution attempt at 30 seconds, including container startup.
  Claude API latency and input preparation are outside this execution budget.
  Shorter configured timeouts are allowed. A timeout is not retried.
- At timeout, force-remove that run's uniquely named container before deleting
  the temporary workspace. Cleanup has its own bounded 5-second control timeout;
  report cleanup failure rather than claiming that the container stopped.
- Mount only the per-run temporary workspace. Never mount repo/home or the
  Docker socket. Retain non-root execution and memory/CPU/PID restrictions.
- “No outside files” means no access to user host files outside that mount.
  Python and installed libraries inside the container remain readable.
- Copy inputs into the workspace. Never modify source bytes on success, error,
  or timeout. Reject output destinations that alias a source, including symlinks
  or hardlinks. Reject symlink/non-file sandbox outputs before copy-out.
- No default logging of datasets, full prompts, generated code, secrets, or full
  tracebacks.

## Backend API

Reuse Python callables; no new HTTP endpoints:

1. `schema_inspector.inspect_many(list[InputFileSpec])`
2. `prompt_builder.build_many(task, schema)`
3. `retry_handler.run_many(prompt, inputs, output_path, config=...)`

Return the existing `ExecutionResult`; interfaces format errors and return only
validated outputs. All input entrypoints must enforce the two-file limit.

## Acceptance fixtures

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

Inner/default merge on `pid` must equal:

```csv
order_id,pid,amount,product_name
1,p1,100,Keyboard
2,p2,200,Mouse
```

Left merge must add `3,p3,300,` as the third row. Compare complete values and
columns, not merely file existence or row count. Source bytes stay unchanged.

## Acceptance criteria

| ID | Criterion | Evidence |
| --- | --- | --- |
| AC1 | Two named files, named schemas, safe paths, and at most two inputs | Schema/prompt tests and mocked-provider integration |
| AC2 | Inner/default and left merge match the complete fixtures; duplicate keys retain all pairs | Deterministic integration plus opt-in real-Claude tests |
| AC3 | Missing/ambiguous keys, null keys, and dtype mismatch return meaningful errors without retry; empty output fails | Mocked scripts through the real subprocess pipeline; opt-in real-Claude checks |
| AC4 | Unsafe code is rejected before either backend starts | AST tests and pipeline integration |
| AC5 | Sources are unchanged on success/failure/timeout; aliased destinations and symlink outputs are rejected | Source-byte assertions for both backends |
| AC6 | Docker has no network, mounts only workspace, caps runtime at 30 seconds, and removes a timed-out container | Mocked runtime tests plus opt-in real-Docker integration |
| AC7 | Existing single-file CLI/Streamlit behavior remains; ordinary tests need no provider credentials or Docker | Full pytest and credential-free pytest |

## Verification gates

- Normal: `uv run pytest` and `env -u ANTHROPIC_API_KEY uv run pytest`.
- Docker: build `snapscript-sandbox:local`, then run
  `SNAPSCRIPT_DOCKER_TESTS=1 uv run pytest tests/integration/test_csv_merge_docker.py`.
- Claude: run
  `SNAPSCRIPT_REAL_PROVIDER=1 uv run pytest tests/integration/test_csv_merge_real_provider.py`
  with a configured key. No credentials are embedded in commands or fixtures.
- Report each gate as passed, failed, or not verified/skipped. Mocked Docker
  commands do not prove container isolation; mocked scripts do not prove Claude
  follows the merge policy. A skipped external gate is not a passed gate.

## Implementation plan

- [x] Add this spec and a short shared SDD workflow to AGENTS.md/CLAUDE.md/README.
- [x] Add regression coverage for the gaps before implementing them.
- [x] Reuse the pipeline; add merge prompt guidance, input/output guards, and Docker
  timeout cleanup. Keep AST checks and path injection intact.
- [x] Run focused tests, repair failures, run the full gates, and record AC evidence.
