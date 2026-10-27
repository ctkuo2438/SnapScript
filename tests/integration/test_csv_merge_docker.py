"""Explicit real-Docker gate; ordinary pytest never contacts the daemon."""

import json
from dataclasses import replace
from io import BytesIO
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
from snapscript.core._sandbox_files import container_identity
from snapscript.core.csv_io import read_csv_preview
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


def test_real_docker_readonly_root_tmpfs_privileges_and_private_workspace(tmp_path, monkeypatch, docker_config):
    code = '''from _snapscript_paths import INPUT_PATHS, OUTPUT_PATH
from pathlib import Path
import pandas as pd
workspace = Path(next(iter(INPUT_PATHS.values()))).parent
root = Path(workspace.anchor)
status = dict(line.split(":", 1) for line in (root / "proc" / "self" / "status").read_text().splitlines() if ":" in line)
root_writable = False
try:
    (root / "snapscript-root-probe").write_text("fixture")
    root_writable = True
except OSError:
    pass
scratch = root / "tmp" / "snapscript-tmpfs-probe"
scratch.write_text("fixture")
pd.DataFrame([{
    "uid": int(status["Uid"].split()[0]),
    "root_writable": root_writable,
    "tmp_writable": scratch.read_text() == "fixture",
    "caps_zero": int(status["CapEff"], 16) == 0,
    "no_new_privs": status["NoNewPrivs"].strip() == "1",
    "seccomp_filter": status["Seccomp"].strip() == "2",
    "seccomp_filters_present": int(status["Seccomp_filters"].strip()) > 0,
    "workspace_private": workspace.stat().st_mode & 0o077 == 0,
}]).to_csv(OUTPUT_PATH, index=False)
'''
    output = tmp_path / "restrictions.csv"
    result, calls = run_mocked_merge(write_inputs(tmp_path), output, "Probe runtime restrictions.", code, monkeypatch, docker_config)
    assert result.success, result.stderr
    actual = pd.read_csv(output)
    assert actual.pop("uid").tolist() == [container_identity()[0]]
    expected = pd.DataFrame([{
        "root_writable": False, "tmp_writable": True, "caps_zero": True,
        "no_new_privs": True,
        "seccomp_filter": True, "seccomp_filters_present": True,
        "workspace_private": True,
    }])
    pd.testing.assert_frame_equal(actual, expected)
    assert len(calls) == 1


@pytest.mark.parametrize("encoding,text", [
    ("utf-8", "café"), ("cp1252", "café"),
    ("big5", "台北測試資料"), ("utf-16", "台北測試資料"),
])
def test_real_docker_encoded_outputs_match_preview_and_bytes(tmp_path, monkeypatch, docker_config, encoding, text):
    output = tmp_path / "encoded.csv"
    code = (
        "from _snapscript_paths import OUTPUT_PATH\nimport pandas as pd\n"
        f"pd.DataFrame({{'name': [{text!r}] * 10}}).to_csv(OUTPUT_PATH, index=False, encoding={encoding!r})\n"
    )
    result, calls = run_mocked_merge(write_inputs(tmp_path), output, "Create named rows.", code, monkeypatch, docker_config)
    assert result.success, result.stderr
    expected = pd.DataFrame({"name": [text] * 10})
    pd.testing.assert_frame_equal(read_csv_preview(output, nrows=100), expected)
    buffer = BytesIO()
    expected.to_csv(buffer, index=False, encoding=encoding)
    assert output.read_bytes() == buffer.getvalue()
    assert len(calls) == 1


def test_real_docker_oversized_output_is_not_committed(tmp_path, monkeypatch, docker_config):
    output = tmp_path / "large.csv"
    code = "from _snapscript_paths import OUTPUT_PATH\nimport pandas as pd\npd.DataFrame({'value': ['x' * 1000]}).to_csv(OUTPUT_PATH, index=False)\n"
    config = replace(docker_config, max_output_file_size_bytes=16)
    result, calls = run_mocked_merge(write_inputs(tmp_path), output, "Create rows.", code, monkeypatch, config)
    assert not result.success and "Output exceeds size limit" in result.stderr
    assert not output.exists()
    assert len(calls) == 1


def test_real_docker_capture_limit_removes_container(tmp_path, monkeypatch, docker_config):
    names = []
    original = _docker_runtime.build_command
    def record(workspace, config):
        command = original(workspace, config)
        names.append(command[command.index("--name") + 1])
        return command
    monkeypatch.setattr(_docker_runtime, "build_command", record)
    config = replace(docker_config, max_capture_bytes=2048, docker_timeout_seconds=10)
    result, calls = run_mocked_merge(
        write_inputs(tmp_path), tmp_path / "out.csv", "Create rows.",
        "while True:\n    print('x' * 1024)\n", monkeypatch, config,
    )
    assert not result.success and result.exit_code == -2
    assert "cleanup failed" not in result.stderr.lower()
    assert len(result.stdout.encode("utf-8")) <= 2048
    assert len(calls) == len(names) == 1
    assert _inspect_container(names[0]) is None


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
            assert host["CapDrop"] == ["ALL"]
            assert "no-new-privileges" in host["SecurityOpt"]
            assert "seccomp=builtin" in host["SecurityOpt"]
            assert host["ReadonlyRootfs"] is True
            assert "size=64m" in host["Tmpfs"]["/tmp"]
            assert inspected["Config"]["User"].split(":")[0] not in ("", "0", "root")
            assert observed["workspace"].stat().st_mode & 0o777 == 0o700
            assert observed["workspace"].parent.stat().st_mode & 0o777 == 0o700
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
