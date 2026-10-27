---
name: snapscript-claude-api-conventions
description: Use for SnapScript Anthropic calls, provider configuration, generation retries, fallback, and API metadata.
---

# Anthropic boundary

- Both generation and rewriting use `core/provider.py` and the Anthropic SDK.
  Keep system and user prompts separate; read provider/model settings from config.
- Use `config.fallback_model` for bounded generation escalation; never hardcode
  model names in business logic. Keep SDK retries distinct from generation retries.
- Set explicit SDK timeout/retry budgets and close the client with its context
  manager. Map SDK failures to safe typed categories, omitting raw requests and
  exception causes from user-visible errors.
- Check the SDK's resolved API key/auth token before a request. Preserve typed
  authentication, permission, missing-model, bad-request, timeout and rate-limit
  categories. Credentials come from the environment, never CLI arguments.
- `temperature=None` omits the sampling parameter. Sonnet 5 rejects sampling
  overrides; pass an explicit value only for a compatible model.
- Capture actual response model, token usage, and latency as metadata; preserve
  metadata from all attempts, including fallback. Never log prompt/data/code/keys.
- Unit tests mock the shared SDK boundary. Real-provider tests require explicit
  `SNAPSCRIPT_REAL_PROVIDER=1`; never make paid calls during ordinary verification.

SDK reference: https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python
Model reference: https://platform.claude.com/docs/en/models/sonnet-5/overview
