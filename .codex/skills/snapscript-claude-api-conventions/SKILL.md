---
name: snapscript-claude-api-conventions
description: |
  Use when calling the Anthropic Claude API from SnapScript. Triggers:
  writing code_generator.py, retry_handler.py, modifying CLAUDE_CONFIG,
  adding API retry logic, handling rate limits, or logging API calls.
  Do NOT use for general Python coding or unrelated parts of SnapScript.
---

# Claude API conventions for SnapScript

## Model selection (per AppConfig)

In config.py:

    default_model: str = "claude-sonnet-4-20250514"
    fallback_model: str = "claude-opus-4-20250514"

NEVER hardcode model names in business logic — always read from AppConfig.

## Required parameters

    {
        "model": config.default_model,
        "max_tokens": 4096,
        "temperature": 0,
    }

temperature=0 is required for code generation. Reasons:
- Reproducibility (same input → same output → easier debugging)
- Deterministic production runs (won't flake)
- Code quality (creativity is not correctness in script generation)

If you ever need temperature > 0, document the specific reason at the call site.

## Model escalation (per TODOS.md decision)

Three-attempt strategy:

    Attempt 1: Sonnet, original prompt
       ↓ if exit_code != 0 with traceback
    Attempt 2: Sonnet, retry prompt with stderr context
       ↓ if still failing
    Attempt 3: Opus (fallback_model), retry prompt with both failures
       ↓ if still failing
    Show user the error, stop

Implementation per TODOS:

    # code_generator.generate accepts optional model override
    def generate(prompt: str, model: str | None = None) -> GeneratedScript:
        model = model or config.default_model
        ...

    # retry_handler passes fallback on attempt 2 (the third overall call)
    def retry(...):
        if attempt == 2:
            return code_generator.generate(retry_prompt, model=config.fallback_model)

## Don't retry when

- Timeout error — logic problem (e.g. O(n²) on big file), not transient
- Safety violation — regenerate likely produces same kind of code; user must rephrase
- API auth error (401/403) — config problem, not transient

## Do retry when

- exit_code != 0 AND stderr contains a Python traceback (logic bug in generated code)
- API rate limit (429) with exponential backoff: 2s, 4s, 8s
- API server error (500/502/503) — same backoff

## Anthropic SDK usage

Use the official client:

    from anthropic import Anthropic

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = client.messages.create(
        model=config.default_model,
        max_tokens=4096,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    code = response.content[0].text
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens

NEVER hand-roll HTTP requests. NEVER concatenate system + user into one
message body — that defeats Anthropic's prompt cache.

## Prompt structure

System prompt and user prompt MUST be SEPARATE arguments.

CORRECT:

    client.messages.create(
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

WRONG:

    client.messages.create(
        messages=[{"role": "user", "content": SYSTEM_PROMPT + user_prompt}],
    )

The system prompt is ~constant across calls. Anthropic caches it for
cheaper re-use. Concatenating defeats the cache and triples cost.

## API key resolution order

    def resolve_api_key(cli_arg: str | None) -> str:
        return (
            cli_arg                                    # 1. --api-key flag
            or os.environ.get("ANTHROPIC_API_KEY")     # 2. env var
            or _read_dotenv_key()                      # 3. .env file (dev only)
            or _raise_missing_key()
        )

NEVER:
- Print API keys in logs, errors, or stack traces
- Commit .env to git (verify it's in .gitignore)
- Pass keys via URL query strings
- Log the full request body

## Required tracking on every API call

Per SDS section 8.2, every call must record:

    @dataclass
    class APICallMetrics:
        model: str
        input_tokens: int
        output_tokens: int
        latency_ms: int
        success: bool
        error_type: str | None = None

Log to stderr in Phase 1. Send to Sentry in Phase 3.

## Privacy: never log content

NEVER:
    logger.info(f"prompt: {messages}")             # leaks user task + schema
    logger.info(f"generated code: {code}")          # might leak schema details
    logger.info(f"file content: {df.head()}")       # leaks user data

OK:
    logger.info(f"api: model={m}, in={ti}, out={to}, ms={lat}")
    logger.info(f"generated {len(code)} chars")
    logger.info(f"file: name={filename}, rows={n}, cols={k}")

## Cost awareness

Sonnet pricing (~2026): $3 input / $15 output per 1M tokens.

Typical SnapScript call:
- input ~1500 tokens (system cached + schema + task)
- output ~400 tokens (the script)
- ~$0.01 per call

Mental model: 100 calls = ~$1. Retries multiply this.

If you find yourself calling the API in a loop without bounded retries,
STOP and add a circuit breaker.

## Prompt iteration is the product (per TODOS Day 8-10)

prompts/system.txt is the most important file in the project. Days 8-10
of the timeline are dedicated to iterating it.

Treat changes to system.txt as carefully as production code changes:
- Each change has a documented reason (e.g. "fixed deduplication on email column")
- Document changes in prompts/CHANGELOG.md
- Run all 10 CLI gate tasks after every change
- Phase 2 gate: 8/10 CLI tasks pass on first attempt without retry

## Output post-processing pipeline

After client.messages.create() returns, before passing to safety_checker:

1. Strip markdown code fences if Claude wrapped the code in ```python ... ```
2. Remove any non-Python prose before/after the code
3. Validate with ast.parse() — if it fails, treat as a generation error and retry
4. Return GeneratedScript with both clean code and raw_response

The raw_response is kept for debugging. The clean code is what goes to
safety_checker and sandbox_executor.

## Circuit breaker for runaway costs

Hard cap on attempts per single user request:

- Maximum 3 API calls per user task (Sonnet, Sonnet, Opus)
- Maximum 1 retry per generation (markdown stripping etc.)
- After exhausting these, surface error to user — do not silently re-call

If a future feature needs more attempts, that's a feature design discussion,
not an implementation detail to quietly relax.
