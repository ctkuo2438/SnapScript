from dataclasses import dataclass, field
import os

from snapscript.core.models import InputValidationError

ALLOWED_SANDBOX_BACKENDS = frozenset({"subprocess", "docker"})
DEFAULT_DOCKER_IMAGE = "snapscript-sandbox:local"
DEFAULT_DOCKER_TIMEOUT_SECONDS = 30
MAX_DOCKER_TIMEOUT_SECONDS = 30
DEFAULT_DOCKER_MEMORY_LIMIT = "512m"
DEFAULT_DOCKER_CPU_LIMIT = "1.0"


@dataclass(frozen=True)
class AppConfig:
    # LLM provider
    llm_provider: str = "anthropic"
    default_model: str = "claude-sonnet-5"
    fallback_model: str = "claude-opus-4-8"
    max_tokens: int = 4096
    # None uses the model default and omits the provider parameter;
    # a float is an explicit override for models that still accept it.
    temperature: float | None = None

    # CLI defaults to subprocess; web defaults to Docker and MCP requires it.
    execution_timeout_seconds: int = 30
    # number of retries after the initial attempt, total attempts = max_retries + 1
    max_retries: int = 2
    max_output_file_size_bytes: int = 100 * 1024 * 1024
    sandbox_backend: str = field(
        default_factory=lambda: _env_string(
            "SNAPSCRIPT_SANDBOX_BACKEND",
            "subprocess",
        )
    )
    docker_image: str = field(
        default_factory=lambda: _env_string(
            "SNAPSCRIPT_DOCKER_IMAGE",
            DEFAULT_DOCKER_IMAGE,
        )
    )
    docker_timeout_seconds: int = field(
        default_factory=lambda: _env_positive_int(
            "SNAPSCRIPT_DOCKER_TIMEOUT_SECONDS",
            DEFAULT_DOCKER_TIMEOUT_SECONDS,
        )
    )
    docker_memory_limit: str = field(
        default_factory=lambda: _env_string(
            "SNAPSCRIPT_DOCKER_MEMORY_LIMIT",
            DEFAULT_DOCKER_MEMORY_LIMIT,
        )
    )
    docker_cpu_limit: str = field(
        default_factory=lambda: _env_string(
            "SNAPSCRIPT_DOCKER_CPU_LIMIT",
            DEFAULT_DOCKER_CPU_LIMIT,
        )
    )
    docker_network_disabled: bool = field(
        default_factory=lambda: _env_bool(
            "SNAPSCRIPT_DOCKER_NETWORK_DISABLED",
            True,
        )
    )

    # File and schema handling
    max_input_file_size_bytes: int = 500 * 1024 * 1024
    schema_sample_rows: int = 5
    schema_inspect_rows: int = 1000
    max_column_name_chars: int = 100

    # Safety
    allowed_imports: frozenset[str] = frozenset(
        {
            "pandas",
            "openpyxl",
            "csv",
            "json",
            "re",
            "datetime",
            "pathlib",
            "collections",
            "itertools",
            "functools",
            "math",
            "decimal",
            "typing",
        }
    )

    # Prompt
    max_prompt_tokens: int = 8000
    overwrite_output: bool = True
    max_capture_bytes: int = 65536
    provider_timeout_seconds: float = 60.0
    provider_max_retries: int = 1

    def __post_init__(self) -> None:
        positive_limits = (
            "max_tokens", "execution_timeout_seconds", "max_output_file_size_bytes",
            "max_input_file_size_bytes", "schema_inspect_rows", "max_column_name_chars",
            "max_prompt_tokens", "max_capture_bytes", "docker_timeout_seconds",
        )
        for name in positive_limits:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise InputValidationError(f"{name} must be a positive integer")
        if self.docker_timeout_seconds > MAX_DOCKER_TIMEOUT_SECONDS:
            raise InputValidationError(f"docker_timeout_seconds must be at most {MAX_DOCKER_TIMEOUT_SECONDS}")
        timeout = self.provider_timeout_seconds
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout < float("inf"):
            raise InputValidationError("provider_timeout_seconds must be a positive finite number")
        for name in ("max_retries", "provider_max_retries", "schema_sample_rows"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InputValidationError(f"{name} must be a non-negative integer")
        if self.temperature is not None and not 0 <= self.temperature <= 1:
            raise InputValidationError("temperature must be between 0 and 1, or None")
        sandbox_backend = self.sandbox_backend.strip().lower()
        if sandbox_backend not in ALLOWED_SANDBOX_BACKENDS:
            raise InputValidationError(
                "SNAPSCRIPT_SANDBOX_BACKEND must be one of: "
                f"{', '.join(sorted(ALLOWED_SANDBOX_BACKENDS))}"
            )
        object.__setattr__(self, "sandbox_backend", sandbox_backend)

        if not self.docker_image.strip():
            raise InputValidationError("SNAPSCRIPT_DOCKER_IMAGE must not be empty")
        if not self.docker_memory_limit.strip():
            raise InputValidationError("SNAPSCRIPT_DOCKER_MEMORY_LIMIT must not be empty")
        if not self.docker_cpu_limit.strip():
            raise InputValidationError("SNAPSCRIPT_DOCKER_CPU_LIMIT must not be empty")


def _env_string(env_name: str, default: str) -> str:
    return os.environ.get(env_name, default).strip()


def _env_positive_int(env_name: str, default: int) -> int:
    raw_value = os.environ.get(env_name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise InputValidationError(f"{env_name} must be a positive integer") from exc
    if value <= 0:
        raise InputValidationError(f"{env_name} must be a positive integer")
    return value


def _env_bool(env_name: str, default: bool) -> bool:
    raw_value = os.environ.get(env_name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise InputValidationError(f"{env_name} must be a boolean value")
