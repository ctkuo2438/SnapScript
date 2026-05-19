from dataclasses import FrozenInstanceError, is_dataclass

import pytest

from snapscript.config import AppConfig


def test_app_config_defaults_cover_phase_1_limits() -> None:
    config = AppConfig()

    assert is_dataclass(config)
    assert config.llm_provider == "anthropic"
    assert config.default_model
    assert config.fallback_model
    assert config.default_model != config.fallback_model
    assert config.max_tokens == 4096
    assert config.temperature == 0.0

    assert config.execution_timeout_seconds == 30
    assert config.max_retries == 2
    assert config.max_output_file_size_bytes > 0

    assert config.max_input_file_size_bytes > 0
    assert config.schema_sample_rows == 5
    assert config.schema_inspect_rows == 1000
    assert config.max_column_name_chars == 100

    assert "pandas" in config.allowed_imports
    assert "subprocess" not in config.allowed_imports
    assert config.max_prompt_tokens > 0


def test_app_config_defaults_to_subprocess_sandbox_backend() -> None:
    config = AppConfig()

    assert config.sandbox_backend == "subprocess"


def test_app_config_default_docker_settings_are_local_and_restricted() -> None:
    config = AppConfig()

    assert config.docker_image == "snapscript-sandbox:local"
    assert config.docker_timeout_seconds == config.execution_timeout_seconds
    assert config.docker_memory_limit == "512m"
    assert config.docker_cpu_limit == "1.0"
    assert config.docker_network_disabled is True


@pytest.mark.parametrize("backend", ["docker", "subprocess"])
def test_app_config_reads_sandbox_backend_from_environment(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SNAPSCRIPT_SANDBOX_BACKEND", backend)

    config = AppConfig()

    assert config.sandbox_backend == backend


def test_app_config_rejects_invalid_sandbox_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SNAPSCRIPT_SANDBOX_BACKEND", "host-python")

    with pytest.raises(ValueError, match="SNAPSCRIPT_SANDBOX_BACKEND"):
        AppConfig()


def test_app_config_reads_docker_settings_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SNAPSCRIPT_DOCKER_IMAGE", "custom-sandbox:dev")
    monkeypatch.setenv("SNAPSCRIPT_DOCKER_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("SNAPSCRIPT_DOCKER_MEMORY_LIMIT", "1g")
    monkeypatch.setenv("SNAPSCRIPT_DOCKER_CPU_LIMIT", "2.0")
    monkeypatch.setenv("SNAPSCRIPT_DOCKER_NETWORK_DISABLED", "false")

    config = AppConfig()

    assert config.docker_image == "custom-sandbox:dev"
    assert config.docker_timeout_seconds == 45
    assert config.docker_memory_limit == "1g"
    assert config.docker_cpu_limit == "2.0"
    assert config.docker_network_disabled is False


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        ("true", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("0", False),
        ("no", False),
    ],
)
def test_app_config_parses_docker_network_boolean_values(
    env_value: str,
    expected: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SNAPSCRIPT_DOCKER_NETWORK_DISABLED", env_value)

    config = AppConfig()

    assert config.docker_network_disabled is expected


@pytest.mark.parametrize("env_value", ["0", "-1", "not-a-number"])
def test_app_config_rejects_invalid_docker_timeout(
    env_value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SNAPSCRIPT_DOCKER_TIMEOUT_SECONDS", env_value)

    with pytest.raises(ValueError, match="SNAPSCRIPT_DOCKER_TIMEOUT_SECONDS"):
        AppConfig()


def test_app_config_construction_does_not_require_docker_or_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SNAPSCRIPT_SANDBOX_BACKEND", raising=False)

    config = AppConfig()

    assert config.sandbox_backend == "subprocess"


def test_app_config_is_immutable() -> None:
    config = AppConfig()

    with pytest.raises(FrozenInstanceError):
        config.default_model = "other-model"


def test_app_config_does_not_store_api_keys() -> None:
    config = AppConfig()

    for field_name, value in config.__dict__.items():
        assert "api_key" not in field_name.lower()
        if isinstance(value, str):
            assert "sk-" not in value
            assert "key" not in value.lower()
