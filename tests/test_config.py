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
