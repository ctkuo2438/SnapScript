"""Provider authentication and typed SDK errors; no network requests."""
import httpx
import pytest
from anthropic import AuthenticationError, BadRequestError, NotFoundError, PermissionDeniedError, RateLimitError

from helpers.provider_helpers import FakeAnthropic, Response
from snapscript.config import AppConfig
from snapscript.core import provider
from snapscript.core.models import PromptPayload
from snapscript.interfaces import errors


def test_missing_credentials_fail_before_sdk_request(monkeypatch):
    client = FakeAnthropic()
    client.api_key = None
    client.auth_token = None
    monkeypatch.setattr(provider, "Anthropic", lambda **kwargs: client)
    with pytest.raises(provider.ProviderCallError) as captured:
        provider.call(PromptPayload("system", "fixture"), "fixture-model", AppConfig())
    assert captured.value.category == "provider_authentication"
    assert client.messages.calls == []
    assert client.closed
    assert "ANTHROPIC_API_KEY" in errors.format_exception_error(captured.value)


@pytest.mark.parametrize("error_type,status,category", [
    (AuthenticationError, 401, "provider_authentication"),
    (PermissionDeniedError, 403, "provider_permission"),
    (NotFoundError, 404, "provider_not_found"),
    (BadRequestError, 400, "provider_bad_request"),
    (RateLimitError, 429, "provider_rate_limit"),
])
def test_sdk_errors_preserve_actionable_categories(monkeypatch, error_type, status, category):
    request = httpx.Request("POST", "https://example.invalid/messages")
    response = httpx.Response(status, request=request)
    monkeypatch.setattr(FakeAnthropic, "response", error_type("private request fixture", response=response, body={}))
    monkeypatch.setattr(provider, "Anthropic", FakeAnthropic)
    with pytest.raises(provider.ProviderCallError) as captured:
        provider.call(PromptPayload("system", "fixture"), "fixture-model", AppConfig())
    assert captured.value.category == category
    assert "private request fixture" not in errors.format_exception_error(captured.value)


def test_auth_token_is_supported_without_an_api_key(monkeypatch):
    client = FakeAnthropic()
    client.api_key = None
    client.auth_token = "fixture-token"
    client.messages.response = Response("print('ok')")
    monkeypatch.setattr(provider, "Anthropic", lambda **kwargs: client)
    assert provider.call(PromptPayload("system", "fixture"), "fixture-model", AppConfig()).text == "print('ok')"
