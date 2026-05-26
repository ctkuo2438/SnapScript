from pathlib import Path
import subprocess
import stat

import pandas as pd

from snapscript.config import AppConfig
from snapscript.core import docker_sandbox_executor
from snapscript.core.models import ExecutionResult, InputFileSpec


def _write_input_csv(path: Path) -> None:
    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [500, 1500, 2500],
        }
    ).to_csv(path, index=False)


def _write_products_csv(path: Path) -> None:
    pd.DataFrame(
        {
            "pid": ["p1", "p2"],
            "product_name": ["Keyboard", "Mouse"],
        }
    ).to_csv(path, index=False)


def _workspace_from_command(command: list[str]) -> Path:
    volume_arg = command[command.index("-v") + 1]
    host_path, _container_path = volume_arg.split(":", 1)
    return Path(host_path)


def test_build_docker_command_uses_default_image_and_workspace_mount(
    tmp_path: Path,
) -> None:
    config = AppConfig()

    command = docker_sandbox_executor._build_docker_command(tmp_path, config)

    assert command[0:3] == ["docker", "run", "--rm"]
    assert "--network" in command
    assert command[command.index("--network") + 1] == "none"
    assert "--memory" in command
    assert command[command.index("--memory") + 1] == config.docker_memory_limit
    assert "--cpus" in command
    assert command[command.index("--cpus") + 1] == config.docker_cpu_limit
    assert "--pids-limit" in command
    assert command[command.index("--pids-limit") + 1] == "128"
    assert command.count("-v") == 1
    assert f"{tmp_path.resolve()}:/workspace" in command
    assert "-w" in command
    assert "/workspace" in command
    assert config.docker_image in command
    assert command[-2:] == ["python", "script.py"]


def test_build_docker_command_omits_network_none_when_network_enabled(
    tmp_path: Path,
) -> None:
    config = AppConfig(docker_network_disabled=False)

    command = docker_sandbox_executor._build_docker_command(tmp_path, config)

    assert "--network" not in command
    assert "none" not in command


def test_build_docker_command_uses_configured_docker_values(
    tmp_path: Path,
) -> None:
    config = AppConfig(
        docker_image="custom-sandbox:dev",
        docker_memory_limit="1g",
        docker_cpu_limit="2.0",
    )

    command = docker_sandbox_executor._build_docker_command(tmp_path, config)

    assert "custom-sandbox:dev" in command
    assert command[command.index("--memory") + 1] == "1g"
    assert command[command.index("--cpus") + 1] == "2.0"


def test_prepare_workspace_permissions_allows_non_root_container_access(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    direct_files = [
        workspace / "input.csv",
        workspace / "script.py",
        workspace / "_snapscript_paths.py",
    ]
    for index, direct_file in enumerate(direct_files):
        direct_file.write_text(f"file {index}", encoding="utf-8")
        direct_file.chmod(0o400)

    nested_dir = workspace / "nested"
    nested_dir.mkdir()
    nested_file = nested_dir / "nested.csv"
    nested_file.write_text("nested", encoding="utf-8")
    nested_file.chmod(0o400)

    docker_sandbox_executor._prepare_workspace_permissions(workspace)

    mode = stat.S_IMODE(workspace.stat().st_mode)
    assert mode == 0o777
    for direct_file in direct_files:
        assert stat.S_IMODE(direct_file.stat().st_mode) == 0o666
    assert stat.S_IMODE(nested_file.stat().st_mode) == 0o400


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
    assert "INPUT_PATHS" in paths_module
    assert "OUTPUT_PATH" in paths_module
    assert '"/workspace/input.csv"' in paths_module
    assert '"/workspace/output.csv"' in paths_module
    assert '{"input": INPUT_PATH}' in paths_module


def test_workspace_helpers_copy_many_inputs_and_write_container_paths(
    tmp_path: Path,
) -> None:
    orders_source = tmp_path / "source_a"
    products_source = tmp_path / "source_b"
    workspace = tmp_path / "workspace"
    orders_source.mkdir()
    products_source.mkdir()
    workspace.mkdir()
    orders_path = orders_source / "orders.csv"
    products_path = products_source / "orders.csv"
    _write_input_csv(orders_path)
    _write_products_csv(products_path)

    copied_inputs = docker_sandbox_executor._copy_inputs_to_workspace(
        [
            InputFileSpec(name="orders", path=orders_path),
            InputFileSpec(name="products", path=products_path),
        ],
        workspace,
    )
    temp_output = workspace / "output.csv"
    docker_sandbox_executor._write_paths_module(
        workspace,
        None,
        temp_output,
        copied_inputs,
    )

    assert copied_inputs["orders"].name.startswith("input_0_orders_")
    assert copied_inputs["products"].name.startswith("input_1_products_")
    assert copied_inputs["orders"].name != copied_inputs["products"].name
    paths_module = (workspace / "_snapscript_paths.py").read_text(
        encoding="utf-8"
    )
    assert "INPUT_PATH = None" in paths_module
    assert '"/workspace/' in paths_module
    assert '"orders"' in paths_module
    assert '"products"' in paths_module
    assert str(orders_source) not in paths_module
    assert str(products_source) not in paths_module


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


def test_execute_prepares_workspace_permissions_before_docker_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_path = tmp_path / "orders.csv"
    output_path = tmp_path / "filtered.csv"
    _write_input_csv(input_path)

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        workspace = _workspace_from_command(command)
        mode = stat.S_IMODE(workspace.stat().st_mode)
        assert mode == 0o777
        for filename in ("input.csv", "script.py", "_snapscript_paths.py"):
            file_mode = stat.S_IMODE((workspace / filename).stat().st_mode)
            assert file_mode == 0o666
        pd.DataFrame({"order_id": [2], "amount": [1500]}).to_csv(
            workspace / "output.csv",
            index=False,
        )
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(docker_sandbox_executor.subprocess, "run", fake_run)

    result = docker_sandbox_executor.execute(
        "print('container run')\n",
        input_path,
        output_path,
    )

    assert result.success is True


def test_execute_many_invokes_mocked_docker_with_named_input_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    orders_path = tmp_path / "orders.csv"
    products_path = tmp_path / "products.csv"
    output_path = tmp_path / "joined.csv"
    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "pid": ["p1", "p2", "p3"],
            "amount": [100, 200, 300],
        }
    ).to_csv(orders_path, index=False)
    _write_products_csv(products_path)
    captured_paths_module: list[str] = []
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        workspace = _workspace_from_command(command)
        paths_module = (workspace / "_snapscript_paths.py").read_text(
            encoding="utf-8"
        )
        captured_paths_module.append(paths_module)
        assert "INPUT_PATH = None" in paths_module
        assert '"/workspace/input_0_orders_orders.csv"' in paths_module
        assert '"/workspace/input_1_products_products.csv"' in paths_module
        pd.DataFrame(
            {"order_id": [1, 2], "pid": ["p1", "p2"], "product_name": ["Keyboard", "Mouse"]}
        ).to_csv(workspace / "output.csv", index=False)
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(docker_sandbox_executor.subprocess, "run", fake_run)

    result = docker_sandbox_executor.execute_many(
        "print('container run')\n",
        [
            InputFileSpec(name="orders", path=orders_path),
            InputFileSpec(name="products", path=products_path),
        ],
        output_path,
    )

    assert result.success is True
    assert len(commands) == 1
    assert commands[0].count("-v") == 1
    assert output_path.exists()
    output = pd.read_csv(output_path)
    assert output["order_id"].tolist() == [1, 2]
    assert str(tmp_path) not in captured_paths_module[0]


def test_run_docker_uses_configured_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = AppConfig(docker_timeout_seconds=7)
    captured_timeout: list[int] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_timeout.append(int(kwargs["timeout"]))
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(docker_sandbox_executor.subprocess, "run", fake_run)

    result = docker_sandbox_executor._run_docker(
        tmp_path,
        config,
        start_time=0.0,
    )

    assert result.success is True
    assert captured_timeout == [7]


def test_run_docker_returns_failure_on_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = AppConfig(docker_timeout_seconds=3)

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=3,
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr(docker_sandbox_executor.subprocess, "run", fake_run)

    result = docker_sandbox_executor._run_docker(
        tmp_path,
        config,
        start_time=0.0,
    )

    assert result.success is False
    assert result.exit_code == -1
    assert result.stdout == "partial stdout"
    assert "timed out after 3 seconds" in result.stderr
    assert "partial stderr" in result.stderr


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
