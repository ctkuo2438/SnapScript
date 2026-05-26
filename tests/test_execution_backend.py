from pathlib import Path

import pytest

from snapscript.config import AppConfig
from snapscript.core.models import ExecutionResult, InputFileSpec


def _success(stdout: str) -> ExecutionResult:
    return ExecutionResult(success=True, stdout=stdout, exit_code=0)


def test_subprocess_backend_routes_to_sandbox_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from snapscript.core import execution_backend

    calls: list[tuple[str, Path, Path]] = []
    docker_calls = 0
    expected = _success("subprocess")

    def fake_subprocess_execute(
        code: str, input_path: Path, output_path: Path
    ) -> ExecutionResult:
        calls.append((code, input_path, output_path))
        return expected

    def fake_docker_execute(
        code: str, input_path: Path, output_path: Path
    ) -> ExecutionResult:
        nonlocal docker_calls
        docker_calls += 1
        return _success("docker")

    monkeypatch.setattr(
        execution_backend.sandbox_executor,
        "execute",
        fake_subprocess_execute,
    )
    monkeypatch.setattr(
        execution_backend.docker_sandbox_executor,
        "execute",
        fake_docker_execute,
    )

    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    result = execution_backend.execute(
        "code",
        input_path,
        output_path,
        AppConfig(sandbox_backend="subprocess"),
    )

    assert result is expected
    assert calls == [("code", input_path, output_path)]
    assert docker_calls == 0


def test_docker_backend_routes_to_docker_sandbox_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from snapscript.core import execution_backend

    subprocess_calls = 0
    calls: list[tuple[str, Path, Path]] = []
    expected = _success("docker")

    def fake_subprocess_execute(
        code: str, input_path: Path, output_path: Path
    ) -> ExecutionResult:
        nonlocal subprocess_calls
        subprocess_calls += 1
        return _success("subprocess")

    def fake_docker_execute(
        code: str, input_path: Path, output_path: Path
    ) -> ExecutionResult:
        calls.append((code, input_path, output_path))
        return expected

    monkeypatch.setattr(
        execution_backend.sandbox_executor,
        "execute",
        fake_subprocess_execute,
    )
    monkeypatch.setattr(
        execution_backend.docker_sandbox_executor,
        "execute",
        fake_docker_execute,
    )

    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    result = execution_backend.execute(
        "code",
        input_path,
        output_path,
        AppConfig(sandbox_backend="docker"),
    )

    assert result is expected
    assert subprocess_calls == 0
    assert calls == [("code", input_path, output_path)]


def test_subprocess_backend_routes_multi_file_inputs_to_sandbox_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from snapscript.core import execution_backend

    calls: list[tuple[str, list[InputFileSpec], Path]] = []
    expected = _success("subprocess multi")

    def fake_subprocess_execute_many(
        code: str, inputs: list[InputFileSpec], output_path: Path
    ) -> ExecutionResult:
        calls.append((code, inputs, output_path))
        return expected

    monkeypatch.setattr(
        execution_backend.sandbox_executor,
        "execute_many",
        fake_subprocess_execute_many,
        raising=False,
    )

    inputs = [
        InputFileSpec(name="orders", path=tmp_path / "orders.csv"),
        InputFileSpec(name="products", path=tmp_path / "products.csv"),
    ]
    output_path = tmp_path / "output.csv"
    result = execution_backend.execute(
        "code",
        inputs,
        output_path,
        AppConfig(sandbox_backend="subprocess"),
    )

    assert result is expected
    assert calls == [("code", inputs, output_path)]


def test_docker_backend_routes_multi_file_inputs_to_docker_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from snapscript.core import execution_backend

    calls: list[tuple[str, list[InputFileSpec], Path]] = []
    expected = _success("docker multi")

    def fake_docker_execute_many(
        code: str, inputs: list[InputFileSpec], output_path: Path
    ) -> ExecutionResult:
        calls.append((code, inputs, output_path))
        return expected

    monkeypatch.setattr(
        execution_backend.docker_sandbox_executor,
        "execute_many",
        fake_docker_execute_many,
        raising=False,
    )

    inputs = [
        InputFileSpec(name="orders", path=tmp_path / "orders.csv"),
        InputFileSpec(name="products", path=tmp_path / "products.csv"),
    ]
    output_path = tmp_path / "output.csv"
    result = execution_backend.execute(
        "code",
        inputs,
        output_path,
        AppConfig(sandbox_backend="docker"),
    )

    assert result is expected
    assert calls == [("code", inputs, output_path)]


def test_config_none_defaults_to_subprocess_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from snapscript.core import execution_backend

    calls: list[tuple[str, Path, Path]] = []
    docker_calls = 0
    expected = _success("default")

    def fake_subprocess_execute(
        code: str, input_path: Path, output_path: Path
    ) -> ExecutionResult:
        calls.append((code, input_path, output_path))
        return expected

    def fake_docker_execute(
        code: str, input_path: Path, output_path: Path
    ) -> ExecutionResult:
        nonlocal docker_calls
        docker_calls += 1
        return _success("docker")

    monkeypatch.delenv("SNAPSCRIPT_SANDBOX_BACKEND", raising=False)
    monkeypatch.setattr(
        execution_backend.sandbox_executor,
        "execute",
        fake_subprocess_execute,
    )
    monkeypatch.setattr(
        execution_backend.docker_sandbox_executor,
        "execute",
        fake_docker_execute,
    )

    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    result = execution_backend.execute("code", input_path, output_path)

    assert result is expected
    assert calls == [("code", input_path, output_path)]
    assert docker_calls == 0


def test_invalid_backend_fails_clearly(tmp_path: Path) -> None:
    from snapscript.core import execution_backend

    class FakeConfig:
        sandbox_backend = "invalid"

    with pytest.raises(ValueError, match="Unsupported sandbox backend: invalid"):
        execution_backend.execute(
            "code",
            tmp_path / "input.csv",
            tmp_path / "output.csv",
            FakeConfig(),
        )


def test_execution_backend_has_no_provider_or_ui_dependencies() -> None:
    source = Path("src/snapscript/core/execution_backend.py").read_text(
        encoding="utf-8"
    )

    forbidden = [
        "argparse",
        "rich",
        "streamlit",
        "anthropic",
        "code_generator",
        "safety_checker",
        "Tauri",
        "MCP",
    ]
    for dependency in forbidden:
        assert dependency not in source
