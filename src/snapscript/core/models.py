'''
for internal data models used across the application, not use for external API models
'''
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
# represents metadata about a single column in the input data
class ColumnInfo:
    name: str
    dtype: str
    null_count: int = 0
    unique_count: int = 0
    sample_values: list[str] = field(default_factory=list)


@dataclass
# represents the overall schema and metadata of the input file, used for prompt generation and safety checks
class SchemaReport:
    filename: str
    file_type: str
    row_count: int
    file_size_bytes: int
    columns: list[ColumnInfo] = field(default_factory=list)
    sample_rows: list[dict[str, object]] = field(default_factory=list)
    encoding: str = "utf-8"
    sheet_names: list[str] = field(default_factory=list)


# we need to know this path's logical name when we have multiple input files
'''
InputFileSpec(
    name="orders",
    path=Path("orders.csv"),
)
'''
@dataclass
class InputFileSpec:
    name: str
    path: Path
    sheet: str | None = None
    display_filename: str | None = None


# we could know the name of the input file and its schema report after inspection
'''
NamedSchemaReport(
    name="orders",
    schema=orders_schema,
)
'''
@dataclass
class NamedSchemaReport:
    name: str
    schema: SchemaReport


'''
MultiFileSchemaReport(
    files=[
        NamedSchemaReport(name="orders", schema=orders_schema),
        NamedSchemaReport(name="products", schema=products_schema),
    ]
)
'''
@dataclass
class MultiFileSchemaReport:
    files: list[NamedSchemaReport] = field(default_factory=list)


@dataclass
# represents the payload for prompt generation, including system and user prompts
class PromptPayload:
    system_prompt: str
    user_prompt: str


@dataclass
# represents the generated code and related metadata after prompt generation
class GeneratedScript:
    code: str
    raw_response: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
# represents the result of safety checks performed on the generated code, including any violations found
class SafetyResult:
    is_safe: bool
    violations: list[str] = field(default_factory=list)
    ast_valid: bool = True


@dataclass
# represents the result of executing the generated code, including success status, output, and any files produced
class ExecutionResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    output_files: list[Path] = field(default_factory=list)
    execution_time_seconds: float = 0.0
    exit_code: int = 0
