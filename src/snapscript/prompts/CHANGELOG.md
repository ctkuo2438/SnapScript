# Prompt Changelog

Track prompt changes during Days 8-10 prompt iteration.

## Unreleased

- Retry instructions preserve the original `INPUT_PATH`/`INPUT_PATHS` contract,
  including one named MCP input. Invalid/empty/truncated generation responses
  share the existing bounded retry budget with repairable execution failures.
- Rewrite inputs are JSON-encoded and delimiters escaped through the same helper
  as generation metadata. The rewrite system prompt treats schema/advice as
  untrusted data and preserves exact decoded names/text.
- Synthetic regressions and complete local outputs are recorded in
  `docs/ai_csv_merge_verification.md`.

## 2026-10-26 First-attempt gate and remaining review verification

- Rebuilt the pinned sandbox image and ran 12 real-container checks, including
  CSV encodings, XLSX/MCP output, source preservation, isolation and cleanup.
- The real first-attempt gate now independently counts one generation per task
  and disables both application and SDK retries. All ten CLI fixtures passed
  on their first attempt with the configured Claude model, executing in Docker;
  the gate took 47.22 seconds. No system prompt tuning was needed.
- The ordinary ten-case CLI regression remains mocked regardless of opt-in flags.
- Runtime prompt files are included in both wheel and sdist; an installed wheel
  successfully loaded system/retry/rewrite prompts outside the source repository.

## 2026-10-10 AI CSV Merge Spec

- Updated multi-file guidance in `core/prompt_builder.py` to follow `specs/csv-merge.md`:
  default inner join, infer only a sole common key, validate actual keys/types/nulls,
  preserve duplicate pairings, and report actionable input errors.
- The first real-provider gate exposed an implicit `pid` to `sku` substitution.
  Clarified that a named shared key must exist verbatim in both inputs; distinct
  key names require an explicit per-input request. Re-tested missing/ambiguous keys.
- `prompts/system.txt` and single-file prompting are unchanged.
- Deterministic and opt-in real-provider verification is recorded in
  `docs/ai_csv_merge_verification.md`.

## 2026-05-15 Task 20 First-attempt Gate Fix

- Command: custom real-provider harness wrapping `code_generator.generate` to count model calls per CLI gate task.
- Result before prompt change: 7/10 first-attempt passes. `task_01`, `task_04`, and `task_09` passed only after retry.
- Failure mode: first attempts treated `OUTPUT_PATH` from `_snapscript_paths.py` as a `pathlib.Path` object and accessed `.suffix`; `task_01` also assigned into a deduplicated DataFrame without copying first.
- Prompt change: clarify that `INPUT_PATH` and `OUTPUT_PATH` are string paths, require safe suffix checks, and instruct generated pandas code to use `.copy()` before assigning to filtered/sorted/deduplicated DataFrames.

## 2026-05-15 Task 19 Real-provider Re-run

- Command: `SNAPSCRIPT_REAL_PROVIDER=1 uv run pytest tests/integration/test_cli_gate_tasks.py`
- Environment check: `ANTHROPIC_API_KEY` visible to this Codex session; verified by presence, length, and a short SHA-256 prefix only.
- Provider/model from config: Anthropic, `claude-sonnet-4-20250514`; fallback `claude-opus-4-20250514`
- Result: 10/10 first-attempt passes.
- Failed task IDs: none.
- Failure mode: none observed. No prompt change was made because the CLI gate exceeded the 8/10 threshold without generated-code failures.

## 2026-05-15 Task 19 Baseline

- Command: `SNAPSCRIPT_REAL_PROVIDER=1 uv run pytest tests/integration/test_cli_gate_tasks.py`
- Provider/model from config: Anthropic, `claude-sonnet-4-20250514`; fallback `claude-opus-4-20250514`
- Result: 0/10 executable task passes; all 10 tasks failed before provider response/code generation completed because credentials were not visible.
- Failed task IDs: `task_01`, `task_02`, `task_03`, `task_04`, `task_05`, `task_06`, `task_07`, `task_08`, `task_09`, `task_10`
- Failure mode: provider/config failure. Each task returned `ProviderCallError: Provider call failed` before safety checking, sandbox execution, or output assertions.
- Follow-up check: `ANTHROPIC_API_KEY` was not visible to `python` or `uv run python` in this execution environment. No prompt change was made because no generated-code failure mode was available to optimize.
