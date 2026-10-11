"""Explicit real-Docker gate; ordinary pytest never contacts the daemon."""

import json
import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest

from snapscript.config import AppConfig
from snapscript.core import _docker_runtime
from merge_helpers import expected_merge, merge_code, run_mocked_merge, write_inputs


pytestmark = pytest.mark.skipif(os.getenv("SNAPSCRIPT_DOCKER_TESTS") != "1", reason="Real Docker is explicit opt-in")


@pytest.mark.parametrize("join", ["inner", "left"])
def test_real_docker_merge_matches_complete_fixture(tmp_path, monkeypatch, docker_config, join):
    output = tmp_path / "merged.csv"
    result, calls = run_mocked_merge(write_inputs(tmp_path), output, "Merge files.", merge_code(join=join), monkeypatch, docker_config)

    assert result.success, result.stderr
    assert len(calls) == 1
    pd.testing.assert_frame_equal(pd.read_csv(output), expected_merge(join))


def test_real_docker_missing_key_preserves_sources(tmp_path, monkeypatch, docker_config):
    inputs = write_inputs(tmp_path, products="sku,product_name\np1,Keyboard\n")
    output = tmp_path / "merged.csv"
    result, calls = run_mocked_merge(inputs, output, "Merge on pid.", merge_code(), monkeypatch, docker_config)

    assert not result.success
    assert "products missing column pid" in result.stderr
    assert len(calls) == 1
    assert not output.exists()


def _inspect_container(name: str) -> dict | None:
    completed = subprocess.run(
        ["docker", "container", "inspect", name], capture_output=True, text=True,
        timeout=5, check=False,
    )
    return json.loads(completed.stdout)[0] if completed.returncode == 0 else None


def test_real_docker_isolation_timeout_and_cleanup(tmp_path, monkeypatch, docker_config):
    observed = {}
    created = threading.Event()
    original_build = _docker_runtime.build_command
    original_remove = _docker_runtime._remove_container
    sentinel_name = f"snapscript-host-only-{uuid.uuid4().hex}.csv"

    def record_command(workspace, config):
        command = original_build(workspace, config)
        observed.update(workspace=workspace, name=command[command.index("--name") + 1])
        observed["sentinel"] = workspace.parent / sentinel_name
        observed["sentinel"].write_text("host only")
        created.set()
        return command

    def record_cleanup(name):
        assert observed["workspace"].exists(), "Cleanup must precede workspace deletion"
        observed["cleanup"] = True
        return original_remove(name)

    monkeypatch.setattr(_docker_runtime, "build_command", record_command)
    monkeypatch.setattr(_docker_runtime, "_remove_container", record_cleanup)
    code = f'''
from _snapscript_paths import INPUT_PATHS, OUTPUT_PATH
from pathlib import Path
outside = Path(INPUT_PATHS["orders"]).parent.parent / {sentinel_name!r}
if outside.exists():
    raise ValueError("Host file unexpectedly visible")
for path in INPUT_PATHS.values():
    with open(path, "w") as stream:
        stream.write("modified workspace copy")
while True:
    pass
'''
    config = AppConfig(sandbox_backend="docker", docker_image=docker_config.docker_image, docker_timeout_seconds=7)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run_mocked_merge, write_inputs(tmp_path), tmp_path / "merged.csv", "Merge files.", code, monkeypatch, config)
            assert created.wait(5), "Docker command was not created"
            deadline = time.monotonic() + 5
            inspected = None
            while inspected is None and time.monotonic() < deadline and not future.done():
                inspected = _inspect_container(observed["name"])
                if inspected is None:
                    time.sleep(0.05)
            assert inspected is not None, "Container could not be inspected"
            host = inspected["HostConfig"]
            assert host["NetworkMode"] == "none"
            assert host["Binds"] == [f'{observed["workspace"]}:/workspace']
            assert host["Memory"] == 512 * 1024 * 1024
            assert host["NanoCpus"] == 1_000_000_000
            assert host["PidsLimit"] == 128
            assert inspected["Config"]["User"] not in ("", "0", "root")
            assert all(not env.startswith("ANTHROPIC_API_KEY=") for env in inspected["Config"]["Env"])
            result, calls = future.result(timeout=15)
        assert not result.success
        assert result.exit_code == -1
        assert "timed out after 7 seconds" in result.stderr
        assert "cleanup failed" not in result.stderr.lower()
        assert len(calls) == 1
        assert observed["cleanup"]
        assert _inspect_container(observed["name"]) is None
        assert not observed["workspace"].exists()
    finally:
        if "sentinel" in observed:
            observed["sentinel"].unlink(missing_ok=True)
