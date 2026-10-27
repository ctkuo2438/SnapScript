"""Explicit MCP integration gates using real Docker and optional real Claude."""

import os
import sys

import pandas as pd
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from snapscript.core import code_generator
from snapscript.core.models import GeneratedScript
from snapscript.interfaces.mcp_server import create_server
from merge_helpers import expected_merge, merge_code, write_inputs


pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(os.getenv("SNAPSCRIPT_DOCKER_TESTS") != "1", reason="Real Docker is explicit opt-in"),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_mcp_real_docker_merge(tmp_path, monkeypatch, docker_config):
    inputs = write_inputs(tmp_path)
    before = [spec.path.read_bytes() for spec in inputs]
    code = merge_code()
    monkeypatch.setattr(code_generator, "generate", lambda *args, **kwargs: GeneratedScript(
        code=code, raw_response=code, model="mock-provider",
    ))
    async with Client(create_server(tmp_path, docker_config), raise_exceptions=True) as client:
        result = await client.call_tool("transform_files", {
            "files": {spec.name: spec.path.name for spec in inputs},
            "task": "Merge orders and products on pid with an inner join.",
            "output_path": "merged.csv",
        })
    assert not result.is_error, result.content
    pd.testing.assert_frame_equal(pd.read_csv(result.structured_content["output_path"]), expected_merge())
    assert [spec.path.read_bytes() for spec in inputs] == before


async def test_mcp_real_docker_xlsx_output(tmp_path, monkeypatch, docker_config):
    source = tmp_path / "orders.xlsx"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame({"amount": [100, 200]}).to_excel(writer, sheet_name="Orders", index=False)
        pd.DataFrame({"ignored": [999]}).to_excel(writer, sheet_name="Other", index=False)
    before = source.read_bytes()
    code = '''from _snapscript_paths import INPUT_PATHS, OUTPUT_PATH
import pandas as pd
frame = pd.read_excel(INPUT_PATHS["orders"], sheet_name="Orders")
frame[frame["amount"] > 100].to_excel(OUTPUT_PATH, index=False)
'''
    monkeypatch.setattr(code_generator, "generate", lambda *a, **k: GeneratedScript(code, code, "fixture"))
    async with Client(create_server(tmp_path, docker_config), raise_exceptions=True) as client:
        result = await client.call_tool("transform_files", {
            "files": {"orders": source.name}, "task": "Keep amounts over 100", "output_path": "out.xlsx",
        })
    assert not result.is_error, result.content
    pd.testing.assert_frame_equal(pd.read_excel(result.structured_content["output_path"]), pd.DataFrame({"amount": [200]}))
    assert source.read_bytes() == before


@pytest.mark.skipif(os.getenv("SNAPSCRIPT_REAL_PROVIDER") != "1", reason="Real provider is explicit opt-in")
async def test_mcp_stdio_real_claude_and_docker(tmp_path, docker_config):
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("Real provider requires a configured API key")
    inputs = write_inputs(tmp_path)
    before = [spec.path.read_bytes() for spec in inputs]
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "snapscript.interfaces.mcp_server", "--workspace", str(tmp_path)],
        env={"ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"], "SNAPSCRIPT_DOCKER_IMAGE": docker_config.docker_image},
    )
    async with Client(parameters, read_timeout_seconds=120) as client:
        inspected = await client.call_tool("inspect_file_schema", {"files": {spec.name: spec.path.name for spec in inputs}})
        assert not inspected.is_error
        result = await client.call_tool("transform_files", {
            "files": {spec.name: spec.path.name for spec in inputs},
            "task": "Merge orders and products on pid with an inner join.",
            "output_path": "merged.csv",
        })
    assert not result.is_error, result.content
    pd.testing.assert_frame_equal(pd.read_csv(result.structured_content["output_path"]), expected_merge())
    assert [spec.path.read_bytes() for spec in inputs] == before
