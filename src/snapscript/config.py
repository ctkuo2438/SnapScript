from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    # LLM provider
    llm_provider: str = "anthropic"
    default_model: str = "claude-sonnet-4-20250514"
    fallback_model: str = "claude-opus-4-20250514"
    max_tokens: int = 4096
    temperature: float = 0.0

    # Execution
    execution_timeout_seconds: int = 30
    max_retries: int = 2
    max_output_file_size_bytes: int = 100 * 1024 * 1024

    # File and schema handling
    max_input_file_size_bytes: int = 500 * 1024 * 1024
    schema_sample_rows: int = 5
    schema_inspect_rows: int = 1000
    max_column_name_chars: int = 100

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
    max_prompt_tokens: int = 8000
