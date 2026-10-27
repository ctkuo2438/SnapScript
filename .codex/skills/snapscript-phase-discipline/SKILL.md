---
name: snapscript-phase-discipline
description: Use for SnapScript features, architecture, scope, roadmap, or dependency changes.
---

# Phase and scope

Read `AGENTS.md` before feature work. Consult local-only `specs/` and
`docs/development.md` when available; otherwise establish expected behavior from
the user's requirements and source/tests. Keep plans/specifications/evidence local.
The active scope is Phase 4A: one or two CSV/XLSX inputs. CLI, Streamlit, Docker,
and the local MCP interface already exist; preserve them.

- Keep `--file input.csv` compatible and accept exactly two named inputs in multi-file mode.
- Do not expand to unlimited files, databases, cloud execution, auth, billing,
  dashboards, persistent history, or runtime agent frameworks without user scope.
- Use the existing core pipeline. Add a module or dependency only when it removes
  duplication or solves a concrete approved requirement; prefer the standard library.
- Implement missing spec behavior, add meaningful regressions, and record actual
  acceptance evidence in the relevant verification document.
- Normal tests need neither credentials nor Docker. Real-provider and Docker gates
  remain opt-in, and skipped checks stay unverified.
- Existing user authorization covers routine implementation choices. Ask only when
  a decision materially changes the requested scope or requires missing information.
