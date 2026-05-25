from dataclasses import dataclass, field
import os


ALLOWED_SANDBOX_BACKENDS = frozenset({"subprocess", "docker"})
DEFAULT_DOCKER_IMAGE = "snapscript-sandbox:local"
DEFAULT_DOCKER_TIMEOUT_SECONDS = 30
DEFAULT_DOCKER_MEMORY_LIMIT = "512m"
DEFAULT_DOCKER_CPU_LIMIT = "1.0"


@dataclass(frozen=True)
class AppConfig:
    # LLM provider
    llm_provider: str = "anthropic"
    default_model: str = "claude-sonnet-4-20250514"
    fallback_model: str = "claude-opus-4-20250514"
    max_tokens: int = 4096
    temperature: float = 0.0

    # Execution, default is subprocess sandbox, 
    #   can be switched to docker via SNAPSCRIPT_SANDBOX_BACKEND=docker
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
    max_input_file_size_bytes: int = 500 * 1024 * 1024 # file size over 500 mb will be rejected
    schema_sample_rows: int = 5 # df.head(5) for LLM to understand the data when generating code, can be adjusted based on token limits and complexity of data
    schema_inspect_rows: int = 1000 # number of rows to read when inspecting schema
    max_column_name_chars: int = 100 # each column name will not exceed 100 characters

    # Safety
    allowed_imports: frozenset[str] = frozenset(
        {
            "pandas",
            "pd",
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
    max_prompt_tokens: int = 8000 # about 6000 english words

    def __post_init__(self) -> None:
        sandbox_backend = self.sandbox_backend.strip().lower()
        if sandbox_backend not in ALLOWED_SANDBOX_BACKENDS:
            raise ValueError(
                "SNAPSCRIPT_SANDBOX_BACKEND must be one of: "
                f"{', '.join(sorted(ALLOWED_SANDBOX_BACKENDS))}"
            )
        object.__setattr__(self, "sandbox_backend", sandbox_backend)

        if self.docker_timeout_seconds <= 0:
            raise ValueError(
                "SNAPSCRIPT_DOCKER_TIMEOUT_SECONDS must be a positive integer"
            )
        if not self.docker_image.strip():
            raise ValueError("SNAPSCRIPT_DOCKER_IMAGE must not be empty")
        if not self.docker_memory_limit.strip():
            raise ValueError("SNAPSCRIPT_DOCKER_MEMORY_LIMIT must not be empty")
        if not self.docker_cpu_limit.strip():
            raise ValueError("SNAPSCRIPT_DOCKER_CPU_LIMIT must not be empty")


def _env_string(env_name: str, default: str) -> str:
    return os.environ.get(env_name, default).strip()


def _env_positive_int(env_name: str, default: int) -> int:
    raw_value = os.environ.get(env_name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{env_name} must be a positive integer")
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
    raise ValueError(f"{env_name} must be a boolean value")
