from pathlib import Path
from collections.abc import Callable
import subprocess
import stat
from unittest.mock import Mock

import pandas as pd
import pytest

from snapscript.config import AppConfig
from snapscript.core import _docker_runtime, docker_sandbox_executor
from snapscript.core._sandbox_files import prepare_container_permissions, prepare_workspace
from snapscript.core.models import ExecutionResult, InputFileSpec
from snapscript.core._process import CaptureLimitExceeded


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


def _mock_docker(monkeypatch: pytest.MonkeyPatch, run: Callable[..., subprocess.CompletedProcess[str]]) -> None:
    monkeypatch.setattr(_docker_runtime, "run_process", run)
    monkeypatch.setattr(_docker_runtime.subprocess, "run", run)


def test_build_docker_command_uses_default_image_and_workspace_mount(
    tmp_path: Path,
) -> None:
    config = AppConfig()

    command = _docker_runtime.build_command(tmp_path, config)

    assert command[0:3] == ["docker", "run", "--rm"]
    assert "--network" in command
    assert command[command.index("--network") + 1] == "none"
    assert "--memory" in command
    assert command[command.index("--memory") + 1] == config.docker_memory_limit
    assert "--cpus" in command
    assert command[command.index("--cpus") + 1] == config.docker_cpu_limit
    assert "--pids-limit" in command
    assert command[command.index("--pids-limit") + 1] == "128"
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--security-opt") + 1] == "no-new-privileges"
    assert "seccomp=builtin" in command
    assert "--read-only" in command
    assert "size=64m" in command[command.index("--tmpfs") + 1]
    assert command[command.index("--user") + 1].split(":")[0] != "0"
    assert command.count("-v") == 1
    assert f"{tmp_path.resolve()}:/workspace" in command
    assert "-w" in command
    assert "/workspace" in command
    assert config.docker_image in command
    assert command[-2:] == ["python", "script.py"]


def test_build_docker_command_rejects_network_access(
    tmp_path: Path,
) -> None:
    config = AppConfig(docker_network_disabled=False)

    with pytest.raises(ValueError, match="network"):
        _docker_runtime.build_command(tmp_path, config)


@pytest.mark.parametrize("options,probe_output,expected", [
    ('["name=seccomp,profile=builtin"]', "2\n", True),
    ('["name=seccomp"]', "2\n", True),
    ('["name=seccomp,profile=unconfined"]', "2\n", True),
    ('["name=seccomp,profile=unconfined"]', "0\n", False),
    ('["name=seccomp,profile=builtin"]', "1\n", False),
    ('["name=seccomp,profile=builtin"]', "unexpected", False),
    ('["name=cgroupns"]', "2\n", False),
    ('not-json', "2\n", False),
    ('null', "2\n", False),
])
def test_preflight_requires_effective_seccomp(monkeypatch, options, probe_output, expected):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["timeout"] <= 5
        assert kwargs["max_capture_bytes"] <= 4096
        output = options if command[1] == "info" else probe_output if command[1] == "run" else "image-id"
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(_docker_runtime, "run_process", run)
    result = _docker_runtime.preflight(AppConfig(sandbox_backend="docker"))
    assert (result is None) == expected
    if not expected:
        assert result.error_category == "backend_unavailable"
        assert "seccomp" in result.stderr.lower()
    probes = [command for command in commands if command[1] == "run"]
    if probes:
        assert "seccomp=builtin" in probes[0]
        assert not {"-v", "--mount", "-e", "--env-file"}.intersection(probes[0])
        assert probes[0][probes[0].index("--network") + 1] == "none"


@pytest.mark.parametrize("failure", ["timeout", "capture"])
@pytest.mark.parametrize("cleanup_error", [None, "Container cleanup failed; Docker could not confirm removal"])
def test_preflight_probe_failure_cleans_container_before_stopping(monkeypatch, failure, cleanup_error):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[1] == "run":
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            raise CaptureLimitExceeded("bounded", "")
        output = '["name=seccomp,profile=builtin"]' if command[1] == "info" else "image-id"
        return subprocess.CompletedProcess(command, 0, output, "")

    cleanup = Mock(return_value=cleanup_error)
    monkeypatch.setattr(_docker_runtime, "run_process", run)
    monkeypatch.setattr(_docker_runtime, "_remove_container", cleanup)
    result = _docker_runtime.preflight(AppConfig(sandbox_backend="docker"))
    assert result is not None
    assert result.error_category == "backend_unavailable"
    probe = commands[-1]
    cleanup.assert_called_once_with(probe[probe.index("--name") + 1])
    if cleanup_error:
        assert cleanup_error in result.stderr
    if failure == "timeout":
        assert result.stderr.startswith("Docker security check timed out after 5 seconds")
        assert "seccomp" not in result.stderr.lower()
    else:
        assert "seccomp" in result.stderr.lower()


def test_unfiltered_docker_stops_before_generation(tmp_path, monkeypatch):
    from snapscript.core import code_generator, retry_handler
    from snapscript.core.models import PromptPayload

    def run(command, **kwargs):
        output = '["name=seccomp,profile=unconfined"]' if command[1] == "info" else "0" if command[1] == "run" else "image-id"
        return subprocess.CompletedProcess(command, 0, output, "")

    source = tmp_path / "input.csv"
    source.write_text("value\n1\n")
    generator = Mock()
    monkeypatch.setattr(_docker_runtime, "run_process", run)
    monkeypatch.setattr(code_generator, "generate", generator)
    result = retry_handler.run(PromptPayload("system", "Copy"), source, tmp_path / "out.csv", config=AppConfig(sandbox_backend="docker"))
    assert result.error_category == "backend_unavailable"
    generator.assert_not_called()
    assert not (tmp_path / "out.csv").exists()


def test_build_docker_command_uses_configured_docker_values(
    tmp_path: Path,
) -> None:
    config = AppConfig(
        docker_image="custom-sandbox:dev",
        docker_memory_limit="1g",
        docker_cpu_limit="2.0",
    )

    command = _docker_runtime.build_command(tmp_path, config)

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

    prepare_container_permissions(workspace)

    mode = stat.S_IMODE(workspace.stat().st_mode)
    assert mode == 0o700
    for direct_file in direct_files:
        assert stat.S_IMODE(direct_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(nested_file.stat().st_mode) == 0o400


def test_workspace_helpers_copy_input_and_write_paths_and_script(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "orders.csv"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_input_csv(input_path)
    code = "print('do not alter this code')\n"

    prepare_workspace(workspace, code, [InputFileSpec("input", input_path)],
                      Path("output.csv"), single_file=True, container_root="/workspace")
    temp_input = workspace / "input.csv"

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
    namespace = {}
    exec(paths_module, namespace)
    assert namespace["INPUT_PATHS"] == {"input": namespace["INPUT_PATH"]}


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

    prepare_workspace(workspace, "pass",
        [
            InputFileSpec(name="orders", path=orders_path),
            InputFileSpec(name="products", path=products_path),
        ],
        Path("output.csv"), single_file=False, container_root="/workspace",
    )
    assert (workspace / "input_0.csv").read_bytes() == orders_path.read_bytes()
    assert (workspace / "input_1.csv").read_bytes() == products_path.read_bytes()
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

    _mock_docker(monkeypatch, fake_run)

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
        assert mode == 0o700
        for filename in ("input.csv", "script.py", "_snapscript_paths.py"):
            file_mode = stat.S_IMODE((workspace / filename).stat().st_mode)
            assert file_mode == 0o600
        pd.DataFrame({"order_id": [2], "amount": [1500]}).to_csv(
            workspace / "output.csv",
            index=False,
        )
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    _mock_docker(monkeypatch, fake_run)

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
        assert '"/workspace/input_0.csv"' in paths_module
        assert '"/workspace/input_1.csv"' in paths_module
        pd.DataFrame(
            {"order_id": [1, 2], "pid": ["p1", "p2"], "product_name": ["Keyboard", "Mouse"]}
        ).to_csv(workspace / "output.csv", index=False)
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    _mock_docker(monkeypatch, fake_run)

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

    _mock_docker(monkeypatch, fake_run)

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

    commands = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[1:3] == ["rm", "--force"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=3,
            output="partial stdout",
            stderr="partial stderr",
        )

    _mock_docker(monkeypatch, fake_run)

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
    container_name = commands[0][commands[0].index("--name") + 1]
    assert commands[1] == ["docker", "rm", "--force", container_name]


def test_docker_timeout_accepts_thirty_second_ceiling(tmp_path, monkeypatch) -> None:
    timeouts = []

    def fake_run(command, **kwargs):
        timeouts.append(kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, "", "")

    _mock_docker(monkeypatch, fake_run)
    result = docker_sandbox_executor._run_docker(tmp_path, AppConfig(docker_timeout_seconds=30), 0.0)

    assert result.success
    assert timeouts == [30]


def test_docker_timeout_reports_cleanup_failure(tmp_path, monkeypatch) -> None:
    def fake_run(command, **kwargs):
        if command[1] == "run":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        assert kwargs["timeout"] == 5
        return subprocess.CompletedProcess(command, 1, "", "daemon unavailable")

    _mock_docker(monkeypatch, fake_run)
    result = docker_sandbox_executor._run_docker(tmp_path, AppConfig(), 0.0)

    assert not result.success
    assert "cleanup failed" in result.stderr.lower()


def test_capture_limit_removes_the_container(tmp_path, monkeypatch) -> None:
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        if command[1] == "run":
            raise CaptureLimitExceeded("bounded output", "")
        assert kwargs["timeout"] == 5
        return subprocess.CompletedProcess(command, 0, "", "")
    _mock_docker(monkeypatch, run)
    result = docker_sandbox_executor._run_docker(tmp_path, AppConfig(), 0.0)
    assert not result.success
    assert result.exit_code == -2
    assert result.stdout == "bounded output"
    name = commands[0][commands[0].index("--name") + 1]
    assert commands[1] == ["docker", "rm", "--force", name]


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

    _mock_docker(monkeypatch, fake_run)

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

    _mock_docker(monkeypatch, fake_run)

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
        (workspace / "output.csv").write_bytes(b"\xff\xfe\x00")
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    _mock_docker(monkeypatch, fake_run)

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

    _mock_docker(monkeypatch, fake_run)

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
