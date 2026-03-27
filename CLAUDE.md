## Project: SnapScript

A CLI/web tool that lets users describe data processing tasks in natural 
language, auto-generates Python scripts, and executes them in a local sandbox.
MVP focuses on CSV/Excel processing.

Tech stack: Python, Claude API (anthropic SDK), pandas, Streamlit (Phase 2).
Full SDS: see snapscript-sds.md

## gstack skills available
Use /browse for all web browsing tasks.
Skills (run in sprint order):
/office-hours, /plan-ceo-review, /plan-eng-review, /plan-design-review,
/design-consultation, /review, /investigate, /design-review, /qa, /qa-only,
/cso, /ship, /land-and-deploy, /canary, /benchmark, /document-release, /retro,
/browse, /setup-browser-cookies, /autoplan, /codex, /careful, /freeze, /guard,
/unfreeze, /setup-deploy, /gstack-upgrade

## Dev environment
Use `uv run` instead of `pip install` + `python`. All deps managed by uv.
