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
