# Phase 2 Manual Verification Checklist

## Preconditions

- Install dependencies with `uv sync`.
- Normal pytest must not require provider credentials.
- Optional real-provider checks require `ANTHROPIC_API_KEY` in the local shell.
- Use local Streamlit only.
- Do not commit, paste, screenshot, or log API keys or other secrets.

Real-provider Streamlit checks are manual and require explicit local
credentials. They must not be part of default pytest or CI.

## Start App

```bash
uv run streamlit run app.py
```

## Fixture To Use

Use this file:

```text
tests/fixtures/integration/task_02_orders.csv
```

Use this task text:

```text
Keep only orders where amount is greater than 1000.
```

Expected behavior:

- Output preview appears after a successful Generate click.
- Download button appears after a successful Generate click.
- Downloaded CSV opens successfully.
- Downloaded rows satisfy `amount > 1000`.

## Automated Checks

- [ ] `env -u ANTHROPIC_API_KEY uv run pytest`
- [ ] `uv run pytest tests/test_streamlit_app.py tests/test_streamlit_pipeline_integration.py`
- [ ] Confirm no test in normal pytest calls a real provider.

## Upload Checks

- [ ] Valid `.csv` upload is accepted.
- [ ] Valid `.xlsx` upload is accepted if a fixture is available.
- [ ] Valid `.xls` upload is accepted if a fixture is available.
- [ ] Unsupported `.txt` upload is rejected with `Unsupported file type: .txt`.
- [ ] Oversized upload is rejected if feasible to test locally.
- [ ] After an invalid upload, uploading a valid file clears the upload error.

## Generate Checks

- [ ] Generate is disabled or blocked without an upload.
- [ ] Generate is disabled or blocked with a blank task.
- [ ] Uploading a file does not call the provider or run generated code.
- [ ] Editing task text does not call the provider or run generated code.
- [ ] Generate triggers the run only after an explicit click.

## Preview And Download Checks

- [ ] Preview renders after success.
- [ ] Preview is bounded and does not attempt to show the full output.
- [ ] Download button is hidden before success.
- [ ] Download button appears after success.
- [ ] Failed run does not expose a stale download.
- [ ] Failed run clears stale preview and output state.

## Rate-Limit Checks

- [ ] Remaining runs is shown.
- [ ] First accepted Generate decreases remaining runs on the next rerun.
- [ ] Second immediate Generate shows a cooldown message.
- [ ] Cooldown-blocked attempt does not increment run count.
- [ ] Cooldown-blocked attempt does not call the provider or core pipeline.
- [ ] After 10 accepted runs, Generate is blocked by the session run limit.

## Error Checks

- [ ] Missing upload message is clear.
- [ ] Blank task message is clear.
- [ ] Unsupported suffix message is clear.
- [ ] Cooldown message is clear.
- [ ] Run limit message is clear.
- [ ] Missing provider key/configuration shows a concise provider message.
- [ ] Safety failure shows the safety-checker rejection message.
- [ ] Sandbox failure shows a safe sandbox summary.
- [ ] Full tracebacks are not shown by default.
- [ ] API keys, tokens, passwords, and secret-like values are not displayed.
- [ ] Long error messages are capped.

## Recovery Checks

- [ ] After a provider, safety, or sandbox failure, edit the task and run again if rate limits allow.
- [ ] After an invalid upload, upload a valid file and run if rate limits allow.
- [ ] Successful run clears the previous error.
- [ ] Validation errors do not corrupt a previous successful output.
- [ ] No error permanently locks the UI unless the run limit is reached.

## Real-Provider Note

- Real-provider Streamlit checks are manual only.
- Do not add real-provider Streamlit checks to default pytest or CI.
- Set `ANTHROPIC_API_KEY` only in the local shell/session used for the manual check.
- Unset credentials before running no-provider verification:

```bash
env -u ANTHROPIC_API_KEY uv run pytest
```

- Do not commit `.env` files, shell history with secrets, screenshots containing secrets, or logs containing provider responses.
