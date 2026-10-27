"""Shared Anthropic SDK fake; never opens a network connection."""
from types import SimpleNamespace


class TextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class Response:
    def __init__(self, text: str, *, model: str | None = None, stop_reason: str = "end_turn") -> None:
        self.content = [TextBlock(text)]
        self.usage = SimpleNamespace(input_tokens=12, output_tokens=8)
        self.model = model
        self.stop_reason = stop_reason


class Messages:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeAnthropic:
    instances: list["FakeAnthropic"] = []
    response: object = Response("print('default')")

    def __init__(self, **options: object) -> None:
        self.api_key = "fixture-provider-key"
        self.auth_token = None
        self.options = options
        self.closed = False
        self.messages = Messages(self.response)
        self.instances.append(self)

    def __enter__(self) -> "FakeAnthropic":
        return self

    def __exit__(self, *args: object) -> None:
        self.closed = True
