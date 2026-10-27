"""Behavior regressions for the seven approved P1 review corrections."""

import json
from pathlib import Path
import re
import sys
from unittest.mock import Mock

import pandas as pd
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from streamlit.testing.v1 import AppTest

from snapscript.config import AppConfig
from snapscript.core import _docker_runtime, _sandbox_files, code_generator, docker_sandbox_executor
from snapscript.core import prompt_builder, safety_checker, sandbox_executor, schema_inspector
from snapscript.core.models import ExecutionResult, GeneratedScript, PromptPayload
from snapscript.core._process import CaptureLimitExceeded, run_process
from snapscript.interfaces import cli, mcp_server, web, web_audit


def test_child_does_not_inherit_provider_or_cloud_credentials(tmp_path, monkeypatch):
    source, output = tmp_path / "input.csv", tmp_path / "output.csv"
    source.write_text("amount\n1\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "private-provider-fixture")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "private-cloud-fixture")
    code = """from _snapscript_paths import OUTPUT_PATH
import pandas as pd
environment = pd.io.common.os.environ
pd.DataFrame({'provider': ['ANTHROPIC_API_KEY' in environment],
              'cloud': ['AWS_SECRET_ACCESS_KEY' in environment]}).to_csv(OUTPUT_PATH, index=False)
"""
    assert not safety_checker.check(code).is_safe
    # Exercise environment filtering directly, independently of the AST guard.
    result = sandbox_executor.execute(code, source, output)
    assert result.success, result.stderr
    assert pd.read_csv(output).to_dict("records") == [{"provider": False, "cloud": False}]


def test_cli_redacts_execution_streams_and_traceback(tmp_path, monkeypatch, capsys):
    source = tmp_path / "input.csv"
    source.write_text("amount\n1\n")
    key = "private-provider-fixture"
    monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    result = ExecutionResult(
        success=False, exit_code=1, stdout=f"[red]summary {key}[/red]",
        stderr=f'Traceback (most recent call last):\n  File "script.py", line 1\nValueError: bad row {key}',
    )
    monkeypatch.setattr(cli.retry_handler, "run", lambda *args, **kwargs: result)
    status = cli.main(["Copy rows", "--file", str(source), "--output", str(tmp_path / "out.csv"),
                       "--yes"])
    captured = capsys.readouterr()
    assert status == 3
    assert key not in captured.out + captured.err
    assert "Traceback" not in captured.err
    assert "ValueError: bad row" in captured.err
    assert "[red]" in captured.out  # Untrusted processing summaries are plain text.


@pytest.mark.parametrize("change", ["remove", "replace", "task", "mode"])
def test_real_app_invalidates_results_when_inputs_change(tmp_path, monkeypatch, change):
    monkeypatch.setenv("SNAPSCRIPT_SANDBOX_BACKEND", "subprocess")
    code = """from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd
pd.read_csv(INPUT_PATH).to_csv(OUTPUT_PATH, index=False)
"""
    generate = Mock(return_value=GeneratedScript(code, code, "fixture"))
    monkeypatch.setattr(code_generator, "generate", generate)
    monkeypatch.setattr(web, "AppConfig", lambda: AppConfig(sandbox_backend="subprocess"))
    monkeypatch.setattr(web_audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    app = AppTest.from_file("app.py", default_timeout=10).run()
    app.file_uploader[0].set_value(("input.csv", b"amount\n1\n", "text/csv"))
    app.text_area[0].set_value("Keep all rows").run()
    next(button for button in app.button if button.label == "Generate").click().run()
    assert app.session_state["output_bytes"] is not None
    if change == "remove":
        app.file_uploader[0].set_value(None).run()
    elif change == "replace":
        app.file_uploader[0].set_value(("new.csv", b"amount\n2\n", "text/csv")).run()
    elif change == "task":
        app.text_area[0].set_value("Keep rows where amount > 100").run()
    else:
        app.radio[0].set_value("Two files").run()
    assert not app.exception
    assert app.session_state["output_bytes"] is None
    assert app.session_state["result_preview"] is None
    assert len(app.get("download_button")) == 0
    generate.assert_called_once()
    if change in {"remove", "mode"}:
        assert next(button for button in app.button if button.label == "Generate").disabled


def test_mcp_preserves_destination_created_during_execution(tmp_path, monkeypatch):
    source, output = tmp_path / "input.csv", tmp_path / "result.csv"
    source.write_text("amount\n1\n")
    original = b"valuable\nkeep-me\n"
    monkeypatch.setattr(code_generator, "generate", lambda *args, **kwargs: GeneratedScript("pass", "pass", "fixture"))
    def run(workspace, config, start):
        output.write_bytes(original)
        (workspace / "output.csv").write_text("amount\n99\n")
        return ExecutionResult(success=True)
    monkeypatch.setattr(docker_sandbox_executor, "_run_docker", run)
    monkeypatch.setattr(_docker_runtime, "preflight", lambda config: None)
    tools = mcp_server._Tools(tmp_path, AppConfig(max_retries=0))
    with pytest.raises(ToolError, match="already exists"):
        tools.transform_files({"orders": source.name}, "Copy orders", output.name)
    assert output.read_bytes() == original
    assert source.read_text() == "amount\n1\n"


@pytest.mark.parametrize("backend", [sandbox_executor, docker_sandbox_executor])
def test_output_size_checked_before_host_parser(tmp_path, monkeypatch, backend):
    source, output = tmp_path / "input.csv", tmp_path / "output.csv"
    source.write_text("amount\n1\n")
    code = """from _snapscript_paths import OUTPUT_PATH
with open(OUTPUT_PATH, 'w') as handle:
    handle.write('value\\n' + 'x' * 100 + '\\n')
"""
    if backend is docker_sandbox_executor:
        def run(workspace, config, start):
            (workspace / "output.csv").write_text("value\n" + "x" * 100 + "\n")
            return ExecutionResult(success=True)
        monkeypatch.setattr(backend, "_run_docker", run)
    parser = Mock(side_effect=AssertionError("Oversized output must not be parsed"))
    monkeypatch.setattr(_sandbox_files.pd, "read_csv", parser)
    result = backend.execute(code, source, output, AppConfig(max_output_file_size_bytes=16))
    assert not result.success
    assert "size limit" in result.stderr.lower()
    parser.assert_not_called()
    assert not output.exists()


def test_child_capture_is_bounded(tmp_path):
    source = tmp_path / "input.csv"
    source.write_text("amount\n1\n")
    result = sandbox_executor.execute("print('x' * 70000)\n", source, tmp_path / "output.csv")
    assert not result.success
    assert len(result.stdout.encode()) <= 65536
    assert "capture limit" in result.stderr.lower()


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_process_capture_bounds_both_streams(stream):
    command = [sys.executable, "-c", f"import sys; sys.{stream}.write('x' * 10000)"]
    with pytest.raises(CaptureLimitExceeded) as error:
        run_process(command, timeout=2, max_capture_bytes=128)
    assert len(error.value.stdout.encode()) <= 128
    assert len(error.value.stderr.encode()) <= 128


def test_cli_sheet_selection_reaches_generation_and_result(tmp_path, monkeypatch):
    source, output = tmp_path / "book.xlsx", tmp_path / "total.csv"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame({"amount": [1, 1, 10]}).to_excel(writer, sheet_name="First", index=False)
        pd.DataFrame({"amount": [1, 1, 20]}).to_excel(writer, sheet_name="Second", index=False)
    config = AppConfig(schema_inspect_rows=2, max_retries=0)
    first = prompt_builder.build("Sum amount", schema_inspector.inspect(source, sheet="First", config=config))
    second = prompt_builder.build("Sum amount", schema_inspector.inspect(source, sheet="Second", config=config))
    assert first.user_prompt != second.user_prompt
    def generate(prompt, **kwargs):
        context = json.loads(re.search(r"<schema>\n(.*?)\n</schema>", prompt.user_prompt, re.S).group(1))
        code = (
            "from _snapscript_paths import INPUT_PATH, OUTPUT_PATH\nimport pandas as pd\n"
            f"df = pd.read_excel(INPUT_PATH, sheet_name={context.get('selected_sheet')!r})\n"
            "pd.DataFrame({'total': [df['amount'].sum()]}).to_csv(OUTPUT_PATH, index=False)\n"
        )
        return GeneratedScript(code, code, "fixture")
    monkeypatch.setattr(cli, "AppConfig", lambda: config)
    monkeypatch.setattr(code_generator, "generate", generate)
    assert cli.main(["Sum amount", "--file", str(source), "--sheet", "Second",
                     "--output", str(output), "--yes"]) == 0
    assert pd.read_csv(output).to_dict("records") == [{"total": 22}]


@pytest.mark.parametrize(("text", "stop"), [
    ("import pandas as pd\ndf = pd.DataFrame({'x': [1]})\ndf['y'] = (", "end_turn"),
    ("```python\nimport pandas as pd\ndf['y'] = (\n```", "end_turn"),
    ("import pandas as pd\n", "max_tokens"),
])
def test_incomplete_generation_never_accepts_a_valid_prefix(monkeypatch, text, stop):
    from snapscript.core.models import ProviderCallMetrics, ProviderReply
    response = ProviderReply(text, ProviderCallMetrics("anthropic", "test-model"), stop)
    monkeypatch.setattr(code_generator.provider, "call", lambda *args: response)
    with pytest.raises(code_generator.CodeGenerationError) as captured:
        code_generator.generate(PromptPayload("fixture", "fixture"))
    from snapscript.interfaces.errors import format_exception_error
    assert captured.value.category == "generation_failure"
    assert "configuration" not in format_exception_error(captured.value)
