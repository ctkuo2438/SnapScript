---
name: snapscript-phase-discipline
description: |
  Use when adding features, modules, dependencies, or making architecture
  decisions in SnapScript. Triggers when user asks for new features, you're
  tempted to "while we're here, also add X", or deciding which phase a
  piece of work belongs to. Use to refuse scope creep into later phases.
---

# SnapScript phase discipline

## Real timeline (per TODOS.md)

| Days  | Phase                | Output                                       |
|-------|----------------------|----------------------------------------------|
| 1-7   | Phase 1 — pipeline   | All core modules wired, CLI invokable        |
| 8-10  | Prompt iteration     | system.txt iterated against 10 CLI gate tasks|
| 11-25 | Phase 2 — Streamlit  | Web UI on top of stable core                 |
| 26-30 | User observation     | Watch real users, record failure modes       |

NOT 8 days. NOT one weekend. 30 days total.

## Phase 1 (Days 1-10) — CLI MVP

In scope:
- argparse CLI in interfaces/cli.py
- subprocess.run() sandbox in sandbox_executor.py
- _snapscript_paths.py injection (per TODOS, NOT str.replace)
- Single CSV/Excel processing
- API key via env var or --api-key flag
- rich for CLI output
- All 6 core modules
- Output validation in sandbox_executor (per TODOS)
- 10 CLI gate tasks (the prompt-iteration test set)

Out of scope (resist!):
- Streamlit UI → Phase 2
- Docker sandbox → Phase 3
- Multi-file ops → Future
- Auth → Future
- Cloud execution → Phase 3
- Database persistence → Future

Gate to Phase 2: 8/10 CLI gate tasks pass on FIRST attempt (no retry).
Don't start Streamlit until this gate passes.

## Phase 2 (Days 11-25) — Streamlit

In scope:
- streamlit app in interfaces/web.py
- st.session_state for in-session state
- st.file_uploader, st.dataframe preview
- API key via st.text_input(type="password") in sidebar
- Rate limiting per TODOS #1: 10 runs/session, 5s cooldown
- All Phase 1 features still work via CLI

Out of scope:
- User accounts → Future
- Multi-user → Future
- Cloud-hosted execution → Phase 3+
- Persistent execution history → Future

## Phase 3 — Tauri / hardening (post-PMF)

In scope:
- Docker sandbox replacing subprocess
- Tauri desktop wrapper
- FastAPI bridge (Tauri Rust ↔ Python)
- Production logging (Sentry)
- Auto-update mechanism

## Out of scope ENTIRELY (per SDS section 1.3)

These are NOT in the roadmap. Don't quietly add them:
- Data visualization / chart generation
- Database connections (Postgres, MySQL, etc.)
- Web scraping
- Cloud execution as a service
- User accounts / team collaboration
- Non-structured data (PDFs, images, contracts)
- Multi-step pipeline chaining

If a user requests one of these, politely note it's out of scope and ask
if they want a one-off workaround vs. a roadmap discussion.

## Decision protocol when asked for a feature

    User asks for X
      ↓
    Is X in current phase scope?
    ├── Yes → Implement
    └── No
       ↓
       Is X in a later phase?
       ├── Yes → "Planned for Phase N. Add now (delays current) or defer?"
       └── No
          ↓
          Is X in "out of scope entirely"?
          ├── Yes → "Out of scope per SDS section 1.3. Discuss roadmap?"
          └── Unclear → ASK before implementing

## Common scope-creep patterns to refuse

"While we're here, let's also add..."
NO. Mark as a separate task, separate PR. Each PR should be one thing.

"It would be easy to also support PDF..."
NO. PDFs are a different file family with different parsing libs and a
different threat surface (PDFs can carry JS).

"What if the user wants to chain multiple operations?"
NO. Multi-step pipelines = a different product. Single-shot is the value prop.

"Let's add a config UI..."
NO. Phase 1 has CLI flags + env vars. UI = Phase 2.

"Should we cache results?"
NO for Phase 1. The point is one-shot. Caching adds invalidation complexity.
Re-evaluate in Phase 3 if real users need it.

"Easy to also add a Slack bot..."
NO. Future. Don't blur the surface area while the core product isn't proven.

## When proposing architecture changes

Before suggesting a refactor, check:

1. Does this serve the CURRENT phase, or speculatively prepare for later?
2. If later: is the cost of refactoring today < cost of doing it then?
3. Does this couple core to a specific interface? (Violates module-conventions skill)

Premature generalization is more expensive than focused MVP execution.

## Dependency additions

Each new entry in pyproject.toml should answer:

- Which phase needs it?
- What's the smallest version that works?
- Is there a stdlib alternative? (Prefer stdlib for sandbox_executor)
- Does it have native deps that complicate Docker (Phase 3)?

Default answer to "should we add this dependency": no, until proven needed.

## Days 8-10 are NOT for new features

Days 8-10 are reserved for prompt iteration on prompts/system.txt only.

If on Day 8 you're tempted to add a new feature instead of iterating
system.txt, STOP. The prompt is the product. Without prompt iteration,
the product doesn't work, regardless of how much code surrounds it.

The gate to start Phase 2 is 8/10 CLI tasks passing without retry.
Code-level work doesn't get you closer to that gate. Prompt iteration does.

## When a user pushes for scope expansion

User: "Can you also add support for parquet?"

WRONG response: "Sure, let me add parquet support."

RIGHT response: "Parquet is out of scope for Phase 1 (CSV/Excel only).
I can either:
1. Add it as a TODOS.md item for future consideration
2. Work around it now if you have a one-off file (manual conversion)
3. Discuss expanding the Phase 1 scope (would delay the prompt iteration gate)
Which one would help?"

This isn't bureaucracy. It's protecting the 30-day roadmap from death by
a thousand reasonable requests.
