---
name: snapscript-safety-rules
description: Use for SnapScript generation, prompts, AST checks, path injection, sandbox execution, and safety tests.
---

# Execution safety

Follow `AGENTS.md`. Consult local-only `specs/csv-merge.md`, `specs/mcp.md` and
`docs/docker_sandbox.md` when available; otherwise use the user's requirements
and source/tests to establish the relevant contracts.

- Always run the AST safety scan before generated code executes.
- AST checks reject known unsafe syntax; they cannot prove arbitrary Python safe.
  Docker is the execution isolation boundary. Block dangerous builtin references,
  dunder/module attributes, and unsafe literal I/O paths/URLs. Dynamic paths and
  arbitrary callable aliases are not resolved by this scan.
- Keep import restrictions separate from column attributes. Allow `__name__`,
  ordinary `code`/`requests`/`http` columns and URL strings used as data. Block
  known URL openers, home expansion calls and unsafe literal `joinpath` parts.
- Inject paths through `_snapscript_paths.py`: single-file `INPUT_PATH`,
  multi-file `INPUT_PATHS`, and `OUTPUT_PATH`. Never substitute user paths into
  generated source or prompts.
- `open()`, pathlib constructors and pandas I/O remain allowed with safe injected
  paths. Check literal path arguments and path keywords; keep harmless pandas
  conversions and non-path format/delimiter arguments working.
- Subprocess execution is a compatibility backend, not host filesystem isolation.
  Pass only required environment variables, never provider/cloud credentials.
  MCP execution requires Docker. Streamlit defaults to Docker; subprocess there
  needs an explicit opt-in and a visible warning.
- Docker mounts only the per-run workspace, never repo/home/socket; preserve
  network-disabled mode, non-root execution, resource limits,
  the 30-second ceiling, and bounded timeout/capture cleanup.
- Apply `seccomp=builtin` to every container and verify `Seccomp: 2` in bounded
  preflight without host mounts before generation. A daemon default of unconfined
  is acceptable only when the explicit override actually installs a filter.
  Reject unsupported filtering; do not alter host Docker settings automatically.
- Validate Docker timeouts (1–30 seconds) in config. Keep committed outputs 0600.
- Retain capability removal, no-new-privileges, read-only root and the bounded
  `/tmp` tmpfs. Map the caller to a non-root UID/GID; keep workspace directories
  0700 and copied files 0600. Root callers keep a root-owned private parent around
  the nested workspace; never chmod a host workspace world-writable.
- Keep process captures bounded. Reject symlink/non-file, empty, oversized, or
  unreadable outputs before committing. Parse the first output row.
- Keep source bytes intact. Guard aliases and publish a complete staged output
  atomically; MCP must reject an existing destination even if created mid-run.
- Reject truncated or syntactically invalid generated responses whole.
- Escape untrusted schema metadata inside prompt delimiters.
- Never log datasets, full prompts, generated code, environment values, keys, or
  full tracebacks by default. Tests must check legitimate code and known attacks.
