from pathlib import Path

import pytest

from snapscript.config import AppConfig
from snapscript.core import code_generator, provider
from snapscript.core.code_generator import (
    EmptyProviderResponseError,
    InvalidGeneratedCodeError,
    ProviderCallError,
    UnsupportedProviderError,
)
from snapscript.core.models import GeneratedScript, PromptPayload


from helpers.provider_helpers import FakeAnthropic as _FakeAnthropic, Response as _Response, TextBlock as _TextBlock
from types import SimpleNamespace


def _payload() -> PromptPayload:
    return PromptPayload(
        system_prompt="system instructions",
        user_prompt="user prompt with schema",
    )


def test_generate_calls_configured_provider_with_separate_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAnthropic.instances = []
    _FakeAnthropic.response = _Response(
        "Here is the script:\n```python\nimport pandas as pd\nprint('ok')\n```\nDone."
    )
    monkeypatch.setattr(provider, "Anthropic", _FakeAnthropic)
    monkeypatch.setattr(
        code_generator,
        "AppConfig",
        lambda: AppConfig(default_model="default-model", max_tokens=1234),
    )

    generated = code_generator.generate(_payload())

    assert isinstance(generated, GeneratedScript)
    assert generated.code == "import pandas as pd\nprint('ok')"
    assert "Here is the script" in generated.raw_response
    assert generated.model == "default-model"
    assert generated.input_tokens == 12
    assert generated.output_tokens == 8

    call = _FakeAnthropic.instances[0].messages.calls[0]
    assert call["model"] == "default-model"
    assert call["max_tokens"] == 1234
    assert "temperature" not in call
    assert call["system"] == "system instructions"
    assert call["messages"] == [{"role": "user", "content": "user prompt with schema"}]


def test_generate_sends_temperature_when_explicitly_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAnthropic.instances = []
    _FakeAnthropic.response = _Response("```python\nprint('ok')\n```")
    monkeypatch.setattr(provider, "Anthropic", _FakeAnthropic)

    code_generator.generate(_payload(), config=AppConfig(temperature=0.0))

    call = _FakeAnthropic.instances[0].messages.calls[0]
    assert call["temperature"] == 0.0


def test_generate_uses_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAnthropic.instances = []
    _FakeAnthropic.response = _Response("```python\nprint('ok')\n```")
    monkeypatch.setattr(provider, "Anthropic", _FakeAnthropic)

    generated = code_generator.generate(_payload(), model="fallback-model")

    assert generated.model == "fallback-model"
    call = _FakeAnthropic.instances[0].messages.calls[0]
    assert call["model"] == "fallback-model"


def test_generate_rejects_unsupported_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        code_generator,
        "AppConfig",
        lambda: AppConfig(llm_provider="other"),
    )
    monkeypatch.setattr(
        provider,
        "Anthropic",
        lambda: pytest.fail("Anthropic client should not be constructed"),
    )

    with pytest.raises(UnsupportedProviderError):
        code_generator.generate(_payload())


def test_generate_wraps_provider_failures_without_prompt_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAnthropic.instances = []
    _FakeAnthropic.response = RuntimeError("upstream failure for user prompt")
    monkeypatch.setattr(provider, "Anthropic", _FakeAnthropic)

    with pytest.raises(ProviderCallError) as exc_info:
        code_generator.generate(_payload())

    assert str(exc_info.value) == "Provider call failed"
    assert "user prompt" not in str(exc_info.value)


def test_generate_wraps_client_construction_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenAnthropic:
        def __init__(self, **kwargs: object) -> None:
            raise RuntimeError("missing api key")

    monkeypatch.setattr(provider, "Anthropic", BrokenAnthropic)

    with pytest.raises(ProviderCallError) as exc_info:
        code_generator.generate(_payload())

    assert str(exc_info.value) == "Provider call failed"


def test_generate_raises_for_empty_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAnthropic.instances = []
    _FakeAnthropic.response = _Response("   ")
    monkeypatch.setattr(provider, "Anthropic", _FakeAnthropic)

    with pytest.raises(EmptyProviderResponseError):
        code_generator.generate(_payload())


def test_generate_raises_for_invalid_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAnthropic.instances = []
    _FakeAnthropic.response = _Response("```python\nfor\n```")
    monkeypatch.setattr(provider, "Anthropic", _FakeAnthropic)

    with pytest.raises(InvalidGeneratedCodeError):
        code_generator.generate(_payload())


def test_extract_text_skips_thinking_blocks() -> None:
    class _ResponseWithThinking:
        content = [SimpleNamespace(), SimpleNamespace(text=123), _TextBlock("print('hi')")]

    assert provider.extract_text(_ResponseWithThinking()) == "print('hi')"


def test_code_generator_core_has_no_ui_execution_or_safety_dependencies() -> None:
    source = Path("src/snapscript/core/code_generator.py").read_text()

    assert "argparse" not in source
    assert "rich" not in source
    assert "streamlit" not in source
    assert "sys.argv" not in source
    assert "subprocess" not in source
    assert "sandbox_executor" not in source
    assert "safety_checker" not in source
