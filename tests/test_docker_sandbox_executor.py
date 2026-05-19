from pathlib import Path
import subprocess

import pandas as pd

from snapscript.core import docker_sandbox_executor
from snapscript.core.models import ExecutionResult


def _write_input_csv(path: Path) -> None:
    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [500, 1500, 2500],
        }
    ).to_csv(path, index=False)


def _workspace_from_command(command: list[str]) -> Path:
    volume_arg = command[command.index("-v") + 1]
    host_path, _container_path = volume_arg.split(":", 1)
    return Path(host_path)


def test_build_docker_command_uses_default_image_and_workspace_mount(
    tmp_path: Path,
) -> None:
    command = docker_sandbox_executor._build_docker_command(tmp_path)

    assert command[0:3] == ["docker", "run", "--rm"]
    assert "-v" in command
    assert f"{tmp_path.resolve()}:/workspace" in command
    assert "-w" in command
    assert "/workspace" in command
    assert "snapscript-sandbox:local" in command
    assert command[-2:] == ["python", "script.py"]


def test_workspace_helpers_copy_input_and_write_paths_and_script(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "orders.csv"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_input_csv(input_path)
    code = "print('do not alter this code')\n"

    temp_input = docker_sandbox_executor._copy_input_to_workspace(
        input_path,
        workspace,
    )
    temp_output = workspace / "output.csv"
    docker_sandbox_executor._write_paths_module(
        workspace,
        temp_input,
        temp_output,
    )
    docker_sandbox_executor._write_script(workspace, code)

    assert temp_input == workspace / "input.csv"
    assert temp_input.read_bytes() == input_path.read_bytes()
    assert (workspace / "script.py").read_text(encoding="utf-8") == code
    paths_module = (workspace / "_snapscript_paths.py").read_text(
        encoding="utf-8"
    )
    assert "INPUT_PATH" in paths_module
    assert "OUTPUT_PATH" in paths_module
    assert '"/workspace/input.csv"' in paths_module
    assert '"/workspace/output.csv"' in paths_module


def test_execute_invokes_mocked_docker_and_copies_valid_csv_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_path = tmp_path / "orders.csv"
    output_path = tmp_path / "filtered.csv"
    _write_input_csv(input_path)
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        workspace = _workspace_from_command(command)
        pd.DataFrame({"order_id": [2, 3], "amount": [1500, 2500]}).to_csv(
            workspace / "output.csv",
            index=False,
        )
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="filtered rows\n",
            stderr="",
        )

    monkeypatch.setattr(docker_sandbox_executor.subprocess, "run", fake_run)

    result = docker_sandbox_executor.execute(
        "print('container run')\n",
        input_path,
        output_path,
    )

    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert result.exit_code == 0
    assert result.stdout == "filtered rows\n"
    assert result.stderr == ""
    assert result.output_files == [output_path]
    assert output_path.exists()
    assert input_path.exists()
    assert len(commands) == 1
    output = pd.read_csv(output_path)
    assert output["order_id"].tolist() == [2, 3]


def test_execute_returns_failure_when_docker_succeeds_without_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_path = tmp_path / "orders.csv"
    output_path = tmp_path / "missing.csv"
    _write_input_csv(input_path)

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="no output\n",
            stderr="",
        )

    monkeypatch.setattr(docker_sandbox_executor.subprocess, "run", fake_run)

    result = docker_sandbox_executor.execute("print('no output')\n", input_path, output_path)

    assert result.success is False
    assert result.exit_code == 0
    assert "Output file was not created" in result.stderr
    assert not output_path.exists()
    assert input_path.exists()


def test_execute_returns_failure_when_docker_output_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_path = tmp_path / "orders.csv"
    output_path = tmp_path / "empty.csv"
    _write_input_csv(input_path)

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        workspace = _workspace_from_command(command)
        (workspace / "output.csv").write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(docker_sandbox_executor.subprocess, "run", fake_run)

    result = docker_sandbox_executor.execute("print('empty')\n", input_path, output_path)

    assert result.success is False
    assert "Output is empty" in result.stderr
    assert not output_path.exists()
    assert input_path.exists()


def test_execute_returns_failure_when_docker_output_is_unreadable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_path = tmp_path / "orders.csv"
    output_path = tmp_path / "broken.csv"
    _write_input_csv(input_path)

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        workspace = _workspace_from_command(command)
        (workspace / "output.csv").write_bytes(b"\xff\xfe\x00not-a-valid-csv")
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(docker_sandbox_executor.subprocess, "run", fake_run)

    result = docker_sandbox_executor.execute("print('broken')\n", input_path, output_path)

    assert result.success is False
    assert "Output unreadable" in result.stderr
    assert not output_path.exists()
    assert input_path.exists()


def test_execute_returns_failure_when_docker_command_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_path = tmp_path / "orders.csv"
    output_path = tmp_path / "failed.csv"
    _write_input_csv(input_path)

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            returncode=17,
            stdout="stdout from docker\n",
            stderr="stderr from docker\n",
        )

    monkeypatch.setattr(docker_sandbox_executor.subprocess, "run", fake_run)

    result = docker_sandbox_executor.execute("raise RuntimeError()\n", input_path, output_path)

    assert result.success is False
    assert result.exit_code == 17
    assert result.stdout == "stdout from docker\n"
    assert result.stderr == "stderr from docker\n"
    assert result.output_files == []
    assert not output_path.exists()
    assert input_path.exists()


def test_docker_executor_core_has_no_provider_or_ui_dependencies() -> None:
    source = Path("src/snapscript/core/docker_sandbox_executor.py").read_text(
        encoding="utf-8"
    )

    assert "argparse" not in source
    assert "rich" not in source
    assert "streamlit" not in source
    assert "Anthropic" not in source
    assert "code_generator" not in source
    assert "safety_checker" not in source
    assert ".generate(" not in source
