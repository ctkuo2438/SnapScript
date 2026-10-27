---
name: snapscript-module-conventions
description: Use when changing SnapScript Python modules, dataclasses, or module boundaries.
---

# Module boundaries

- `core/` owns schema inspection, prompt construction, provider calls, safety,
  retries, and execution. It must not import Streamlit, argparse/click, or rich,
  read CLI arguments, or manipulate UI session state.
- `interfaces/` owns CLI, Streamlit, and MCP input collection and presentation.
  Keep each interface thin and reuse core validation and transformation logic.
- Shared data contracts live in `core/models.py`; `AppConfig` stays frozen in
  `config.py`. Append new dataclass fields with defaults for compatibility.
- Use type annotations, `Path` for core file paths, and Python 3.10 union syntax.
- Raise typed safe exceptions across the core boundary. Interfaces format messages.
- Use the shared `ErrorCategory` literal for failures. Set categories at their
  source; retry decisions and CLI status must not parse human-readable messages.
- Prefer focused functions and shared helpers for repeated behavior. Review
  functions over 50 lines and modules over 300 lines; declarative tables and
  cohesive code may justify length. Do not split solely to meet a line count.
- Avoid unused wrappers, one-use abstractions, class hierarchies for two backends,
  and speculative extension points. Keep tests aimed at observable behavior.
