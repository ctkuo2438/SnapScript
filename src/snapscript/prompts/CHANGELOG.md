# Prompt Changelog

Track prompt changes during Days 8-10 prompt iteration.

## Unreleased

- Initial changelog for prompt iteration notes.

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
