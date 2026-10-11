from pathlib import Path

import pytest

from snapscript.core import docker_sandbox_executor, sandbox_executor
from snapscript.core.models import ExecutionResult, InputFileSpec


@pytest.fixture(params=[sandbox_executor, docker_sandbox_executor], ids=["subprocess", "docker"])
def executor(request):
    return request.param


@pytest.fixture
def inputs(tmp_path: Path) -> list[InputFileSpec]:
    specs = [InputFileSpec(name=name, path=tmp_path / f"{name}.csv") for name in ("orders", "products")]
    for spec in specs:
        spec.path.write_text("pid\np1\n")
    return specs


@pytest.mark.parametrize("alias", ["same", "symlink", "hardlink"])
def test_executor_rejects_source_output_alias(executor, inputs, tmp_path, monkeypatch, alias):
    source = inputs[0].path
    output = source if alias == "same" else tmp_path / "alias.csv"
    if alias == "symlink":
        output.symlink_to(source)
    elif alias == "hardlink":
        output.hardlink_to(source)

    def unexpected_run(*args, **kwargs):
        pytest.fail("Aliased output must be rejected before execution")

    run_name = "_run_script" if executor is sandbox_executor else "_run_docker"
    monkeypatch.setattr(executor, run_name, unexpected_run)

    result = executor.execute_many("print('unused')", inputs, output)

    assert not result.success
    assert "overwrite" in result.stderr
    assert source.read_text() == "pid\np1\n"


@pytest.mark.parametrize("exit_code", [0, 1, -1], ids=["success", "failure", "timeout"])
def test_source_bytes_survive_workspace_writes(executor, inputs, tmp_path, monkeypatch, exit_code):
    original = [spec.path.read_bytes() for spec in inputs]

    def fake_run(workspace, config, start_time):
        for copied_input in workspace.glob("input_*.csv"):
            copied_input.write_text("overwritten workspace copy")
        (workspace / "output.csv").write_text("pid\np1\n")
        return ExecutionResult(success=exit_code == 0, exit_code=exit_code, stderr="" if exit_code == 0 else "failed")

    run_name = "_run_script" if executor is sandbox_executor else "_run_docker"
    monkeypatch.setattr(executor, run_name, fake_run)

    result = executor.execute_many("print('unused')", inputs, tmp_path / "output.csv")

    assert result.success is (exit_code == 0)
    assert [spec.path.read_bytes() for spec in inputs] == original


def test_executor_rejects_symlink_output(executor, inputs, tmp_path, monkeypatch):
    output = tmp_path / "merged.csv"
    output.write_text("existing output")

    def fake_run(workspace, config, start_time):
        (workspace / "output.csv").symlink_to(inputs[0].path)
        return ExecutionResult(success=True)

    run_name = "_run_script" if executor is sandbox_executor else "_run_docker"
    monkeypatch.setattr(executor, run_name, fake_run)

    result = executor.execute_many("print('unused')", inputs, output)

    assert not result.success
    assert "symlink" in result.stderr.lower()
    assert output.read_text() == "existing output"


def test_executor_rejects_third_input(executor, inputs, tmp_path):
    inputs.append(InputFileSpec(name="third", path=tmp_path / "third.csv"))

    result = executor.execute_many("print('unused')", inputs, tmp_path / "merged.csv")

    assert not result.success
    assert "two" in result.stderr
