"""Shared isolation; web provider/backend doubles are explicitly opt-in fixtures."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def isolate_audit_log(monkeypatch, tmp_path):
    from snapscript.interfaces import web_audit

    monkeypatch.setattr(web_audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")


@pytest.fixture
def web_runtime(monkeypatch, isolate_audit_log):
    from helpers.web_helpers import COPY_CODE, METRICS, TASK
    from snapscript.config import AppConfig
    from snapscript.core import code_generator, task_rewriter
    from snapscript.core.models import GeneratedScript, RewrittenTask
    from snapscript.interfaces import web, web_audit

    config = AppConfig(sandbox_backend="subprocess", max_retries=0)
    monkeypatch.setenv("SNAPSCRIPT_SANDBOX_BACKEND", "subprocess")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(web, "AppConfig", lambda: config)
    generate = Mock(return_value=GeneratedScript(COPY_CODE, COPY_CODE, METRICS.model, api_call=METRICS))
    rewrite = Mock(return_value=RewrittenTask(TASK, "Keep all rows.", METRICS.provider, METRICS.model, METRICS))
    monkeypatch.setattr(code_generator, "generate", generate)
    monkeypatch.setattr(task_rewriter, "rewrite_task", rewrite)
    return SimpleNamespace(config=config, generate=generate, rewrite=rewrite, audit_path=web_audit.AUDIT_LOG_PATH)
