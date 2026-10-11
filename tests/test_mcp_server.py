"""MCP contract, host-path boundaries and real core pipeline regressions."""

import json
import os
import sys
from dataclasses import replace
from unittest.mock import Mock

import pandas as pd
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from snapscript.config import AppConfig
from snapscript.core import code_generator, docker_sandbox_executor, sandbox_executor
from snapscript.core.models import ExecutionResult, GeneratedScript
from snapscript.interfaces.mcp_server import create_server


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def files(tmp_path):
    (tmp_path / "orders.csv").write_text("order_id,pid,amount\n1,p1,100\n2,p2,200\n3,p3,300\n")
    (tmp_path / "products.csv").write_text("pid,product_name\np1,Keyboard\np2,Mouse\n")
    return {"orders": "orders.csv", "products": "products.csv"}


@pytest.fixture
def server(tmp_path):
    # Even an explicit subprocess/network-enabled config cannot relax MCP.
    return create_server(tmp_path, AppConfig(
        sandbox_backend="subprocess", docker_network_disabled=False,
        docker_timeout_seconds=90, max_retries=0,
    ))


@pytest.fixture
def generator(monkeypatch):
    mock = Mock(side_effect=AssertionError("Unexpected provider call"))
    monkeypatch.setattr(code_generator, "generate", mock)
    return mock


@pytest.fixture
def docker_executor(monkeypatch):
    def execute_locally(code, inputs, output_path, config):
        # Only the backend is replaced; schema/prompt/AST/output checks are real.
        assert config.sandbox_backend == "docker"
        assert config.docker_network_disabled is True
        assert config.docker_timeout_seconds == 30
        return sandbox_executor.execute_many(
            code, inputs, output_path, config=replace(config, sandbox_backend="subprocess"),
        )

    mock = Mock(side_effect=execute_locally)
    monkeypatch.setattr(docker_sandbox_executor, "execute_many", mock)
    return mock


async def call(server, name, arguments):
    async with Client(server, raise_exceptions=True) as client:
        return await client.call_tool(name, arguments)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_actual_stdio_discovery_inspection_and_errors(tmp_path, files, mode):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "snapscript.interfaces.mcp_server", "--workspace", str(tmp_path)],
        env={"PATH": os.defpath, "ANTHROPIC_API_KEY": ""},
    )
    async with Client(parameters, mode=mode, read_timeout_seconds=10) as client:
        tools = (await client.list_tools()).tools
        assert {tool.name for tool in tools} == {"inspect_file_schema", "transform_files"}
        contracts = {tool.name: tool.input_schema for tool in tools}
        assert contracts["inspect_file_schema"]["required"] == ["files"]
        assert set(contracts["transform_files"]["required"]) == {"files", "task", "output_path"}
        result = await client.call_tool("inspect_file_schema", {"files": files})
        assert not result.is_error
        assert [item["row_count"] for item in result.structured_content["files"]] == [3, 2]
        failed = await client.call_tool("transform_files", {
            "files": files, "task": "Merge on pid", "output_path": "../outside.csv",
        })
        assert failed.is_error
        assert failed.structured_content is None
        assert not (tmp_path.parent / "outside.csv").exists()


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
async def test_inspect_returns_types_without_cell_values(tmp_path, server, generator, suffix):
    frame = pd.DataFrame({"id": [1, 2], "password": ["private-cell-a", "private-cell-b"]})
    path = tmp_path / f"input.{suffix}"
    if suffix == "csv":
        frame.to_csv(path, index=False)
    else:
        frame.to_excel(path, index=False)
    result = await call(server, "inspect_file_schema", {"files": {"input": str(path)}})

    assert not result.is_error
    item = result.structured_content["files"][0]
    assert item["name"] == "input"
    assert item["filename"] == path.name
    assert item["row_count"] == 2
    assert item["columns"] == [{"name": "id", "dtype": "int64"}, {"name": "password", "dtype": "object"}]
    assert item["file_size_bytes"] == path.stat().st_size
    assert item["sheet_names"] == (["Sheet1"] if suffix == "xlsx" else [])
    serialized = result.model_dump_json()
    assert "private-cell" not in serialized
    assert "sample_values" not in serialized and "sample_rows" not in serialized
    generator.assert_not_called()


async def test_schema_column_limit_is_explicit(tmp_path, server, generator):
    pd.DataFrame([{f"c{i}": i for i in range(101)}]).to_csv(tmp_path / "wide.csv", index=False)
    result = await call(server, "inspect_file_schema", {"files": {"wide": "wide.csv"}})
    item = result.structured_content["files"][0]
    assert len(item["columns"]) == 100
    assert item["column_count"] == 101 and item["columns_truncated"] is True
    generator.assert_not_called()


async def test_core_file_size_limit_is_preserved(tmp_path, files, generator):
    server = create_server(tmp_path, AppConfig(max_input_file_size_bytes=1))
    result = await call(server, "inspect_file_schema", {"files": files})
    assert result.is_error and "File too large" in result.content[0].text
    generator.assert_not_called()


async def test_logical_names_are_normalized_by_core(files, server, generator):
    result = await call(server, "inspect_file_schema", {"files": {" orders ": files["orders"]}})
    assert not result.is_error
    assert result.structured_content["files"][0]["name"] == "orders"
    generator.assert_not_called()


@pytest.mark.parametrize("two_files", [False, True])
async def test_transform_matches_complete_expected_csv(tmp_path, files, server, generator, docker_executor, two_files):
    if two_files:
        code = '''from _snapscript_paths import INPUT_PATHS, OUTPUT_PATH
import pandas as pd
orders = pd.read_csv(INPUT_PATHS["orders"])
products = pd.read_csv(INPUT_PATHS["products"])
orders.merge(products, on="pid", how="inner").to_csv(OUTPUT_PATH, index=False)
'''
        expected = pd.DataFrame({"order_id": [1, 2], "pid": ["p1", "p2"], "amount": [100, 200], "product_name": ["Keyboard", "Mouse"]})
    else:
        files = {"orders": files["orders"]}
        code = '''from _snapscript_paths import INPUT_PATHS, OUTPUT_PATH
import pandas as pd
orders = pd.read_csv(INPUT_PATHS["orders"])
orders[orders["amount"] > 100].to_csv(OUTPUT_PATH, index=False)
'''
        expected = pd.DataFrame({"order_id": [2, 3], "pid": ["p2", "p3"], "amount": [200, 300]})
    original = {name: (tmp_path / path).read_bytes() for name, path in files.items()}
    generator.side_effect = None
    generator.return_value = GeneratedScript(code=code, raw_response=code, model="mock")
    result = await call(server, "transform_files", {"files": files, "task": "Process named inputs", "output_path": "result.csv"})

    assert not result.is_error, result.content
    metadata = result.structured_content
    assert metadata["success"] is True and metadata["sandbox_backend"] == "docker"
    assert metadata["output_path"] == str(tmp_path / "result.csv")
    assert metadata["file_size_bytes"] == (tmp_path / "result.csv").stat().st_size
    pd.testing.assert_frame_equal(pd.read_csv(metadata["output_path"]), expected)
    assert {name: (tmp_path / path).read_bytes() for name, path in files.items()} == original
    generator.assert_called_once()
    docker_executor.assert_called_once()
    assert str(tmp_path) not in generator.call_args.args[0].user_prompt
    assert "raw_response" not in json.dumps(metadata) and "stdout" not in metadata


async def test_xlsx_transformation_uses_first_sheet_and_returns_xlsx(tmp_path, server, generator, docker_executor):
    source = tmp_path / "workbook.xlsx"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame({"id": [1, 2], "amount": [100, 200]}).to_excel(writer, sheet_name="Orders", index=False)
        pd.DataFrame({"other": [999]}).to_excel(writer, sheet_name="Other", index=False)
    original = source.read_bytes()
    code = '''from _snapscript_paths import INPUT_PATHS, OUTPUT_PATH
import pandas as pd
frame = pd.read_excel(INPUT_PATHS["orders"])
frame[frame["amount"] > 100].to_excel(OUTPUT_PATH, index=False)
'''
    generator.side_effect = None
    generator.return_value = GeneratedScript(code=code, raw_response=code, model="mock")
    result = await call(server, "transform_files", {
        "files": {"orders": "workbook.xlsx"}, "task": "Keep orders over 100", "output_path": "result.xlsx",
    })
    assert not result.is_error, result.content
    pd.testing.assert_frame_equal(
        pd.read_excel(result.structured_content["output_path"]),
        pd.DataFrame({"id": [2], "amount": [200]}),
    )
    assert source.read_bytes() == original
    docker_executor.assert_called_once()


@pytest.mark.parametrize("invalid_files,message", [
    ({}, "At least one"),
    ({"a": "orders.csv", "b": "orders.csv", "c": "orders.csv"}, "at most two"),
    ({"Orders": "orders.csv"}, "Invalid logical"),
    ({" orders ": "orders.csv", "orders": "orders.csv"}, "Duplicate logical"),
    ({"orders": "missing.csv"}, "File not found"),
    ({"orders": ""}, "must not be empty"),
    ({"orders": "../outside.csv"}, "must not contain"),
    ({"orders": "/etc/passwd"}, "outside"),
    ({"orders": "wrong.txt"}, "Unsupported file type"),
    ({"orders": "folder.csv"}, "not a file"),
    ({"orders": "unreadable.csv"}, "Could not read"),
])
async def test_invalid_inputs_fail_before_generation(tmp_path, files, server, generator, invalid_files, message):
    (tmp_path / "wrong.txt").write_text("not a CSV")
    (tmp_path / "folder.csv").mkdir()
    (tmp_path / "unreadable.csv").write_bytes(b"")
    for name in ("inspect_file_schema", "transform_files"):
        arguments = {"files": invalid_files}
        if name == "transform_files":
            arguments.update(task="Merge", output_path="result.csv")
        result = await call(server, name, arguments)
        assert result.is_error and message in result.content[0].text
    generator.assert_not_called()


@pytest.mark.parametrize("output,message", [
    ("orders.csv", "already exists"),
    ("existing.csv", "already exists"),
    ("", "must not be empty"),
    ("../result.csv", "must not contain"),
    ("/tmp/result.csv", "outside"),
    ("result.py", ".csv or .xlsx"),
    ("missing/result.csv", "parent directory"),
])
async def test_invalid_output_preserves_existing_files(tmp_path, files, server, generator, output, message):
    existing = tmp_path / "existing.csv"
    existing.write_text("keep this file")
    source = (tmp_path / "orders.csv").read_bytes()
    result = await call(server, "transform_files", {"files": files, "task": "Merge", "output_path": output})
    assert result.is_error and message in result.content[0].text
    assert existing.read_text() == "keep this file"
    assert (tmp_path / "orders.csv").read_bytes() == source
    generator.assert_not_called()


async def test_symlink_paths_cannot_escape_workspace(tmp_path, files, server, generator):
    outside = tmp_path.parent / "outside.csv"
    outside.write_text("secret\nnot accessible\n")
    (tmp_path / "link.csv").symlink_to(outside)
    (tmp_path / "linked_directory").symlink_to(tmp_path.parent, target_is_directory=True)
    inspected = await call(server, "inspect_file_schema", {"files": {"input": "link.csv"}})
    transformed = await call(server, "transform_files", {
        "files": files, "task": "Merge", "output_path": "linked_directory/new.csv",
    })
    assert inspected.is_error and transformed.is_error
    assert "outside" in inspected.content[0].text and "outside" in transformed.content[0].text
    generator.assert_not_called()


async def test_hardlink_output_does_not_overwrite_source(tmp_path, files, server, generator):
    source = tmp_path / "orders.csv"
    (tmp_path / "alias.csv").hardlink_to(source)
    original = source.read_bytes()
    result = await call(server, "transform_files", {"files": files, "task": "Merge", "output_path": "alias.csv"})
    assert result.is_error and "already exists" in result.content[0].text
    assert source.read_bytes() == original
    generator.assert_not_called()


async def test_dangling_output_symlink_is_rejected(tmp_path, files, server, generator):
    (tmp_path / "alias.csv").symlink_to(tmp_path / "new.csv")
    result = await call(server, "transform_files", {"files": files, "task": "Merge", "output_path": "alias.csv"})
    assert result.is_error and "must not be a symlink" in result.content[0].text
    assert not (tmp_path / "new.csv").exists()
    generator.assert_not_called()


async def test_empty_task_does_not_call_provider(files, server, generator):
    result = await call(server, "transform_files", {"files": files, "task": " \n ", "output_path": "result.csv"})
    assert result.is_error and "Task must not be empty" in result.content[0].text
    generator.assert_not_called()


async def test_unsafe_code_is_rejected_before_docker(tmp_path, files, server, generator, docker_executor):
    generator.side_effect = None
    generator.return_value = GeneratedScript(code="import os", raw_response="import os", model="mock")
    result = await call(server, "transform_files", {"files": files, "task": "Merge", "output_path": "result.csv"})
    assert result.is_error and "Safety violation" in result.content[0].text
    docker_executor.assert_not_called()
    assert not (tmp_path / "result.csv").exists()


async def test_missing_column_error_keeps_context_and_hides_traceback(tmp_path, files, server, generator, docker_executor):
    code = 'raise ValueError("Input validation: products missing column sku; available columns: pid, product_name")'
    generator.side_effect = None
    generator.return_value = GeneratedScript(code=code, raw_response=code, model="mock")
    before = [(tmp_path / path).read_bytes() for path in files.values()]
    result = await call(server, "transform_files", {"files": files, "task": "Merge on sku", "output_path": "result.csv"})
    assert result.is_error
    message = result.content[0].text
    assert "products missing column sku" in message and "pid, product_name" in message
    assert "Traceback" not in message and "raise ValueError" not in message
    assert [(tmp_path / path).read_bytes() for path in files.values()] == before
    assert not (tmp_path / "result.csv").exists()


async def test_provider_error_is_redacted_and_bounded(files, server, generator, docker_executor):
    generator.side_effect = RuntimeError("api_key: fixture-key password: fixture-password sk-ant-fixture-value " + "x" * 2000)
    result = await call(server, "transform_files", {"files": files, "task": "Merge", "output_path": "result.csv"})
    assert result.is_error
    assert "fixture-key" not in result.content[0].text and "fixture-password" not in result.content[0].text
    assert "sk-ant-fixture" not in result.content[0].text and "[REDACTED]" in result.content[0].text
    assert len(result.content[0].text) < 1100
    docker_executor.assert_not_called()


async def test_docker_failure_has_no_output_or_subprocess_fallback(tmp_path, files, server, generator, docker_executor):
    generator.side_effect = None
    generator.return_value = GeneratedScript(code="pass", raw_response="pass", model="mock")
    docker_executor.side_effect = None
    docker_executor.return_value = ExecutionResult(success=False, stderr="Docker unavailable", exit_code=1)
    result = await call(server, "transform_files", {"files": files, "task": "Merge", "output_path": "result.csv"})
    assert result.is_error and "Docker unavailable" in result.content[0].text
    assert result.structured_content is None and not (tmp_path / "result.csv").exists()
