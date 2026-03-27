# SnapScript — Software Design Specifications (SDS)

**Version**: 1.0
**Date**: 2026-03-25
**Status**: Draft

---

## 1. Overview

### 1.1 Product vision

SnapScript 是一個「描述需求，秒生成並執行一次性腳本」的工具。使用者用自然語言描述資料處理任務，系統自動生成 Python 腳本、在安全的 sandbox 中執行、並返回結果。核心價值主張：**No code, no terminal, no Python setup — 10 秒內從問題到答案。**

### 1.2 Target users

**Phase 1-2 的首要使用者**：資料分析師、PM、運營人員——具備一定數據素養，知道自己要對資料做什麼操作，但不想（或不會）寫 Python。

**次要使用者**：開發者——想省去寫一次性腳本的時間，願意用 CLI 快速完成 dirty work。

### 1.3 Scope boundaries (MVP)

**In scope**：CSV/Excel 檔案的資料處理（清洗、篩選、合併、轉換、去重、格式轉換）。

**Out of scope（Phase 1-2 暫不做）**：多檔案關聯分析、資料視覺化/繪圖、資料庫連接、網路爬蟲、雲端執行、帳號系統、團隊協作、非結構化資料（圖片/PDF）處理。

### 1.4 Phased delivery plan

| Phase | 目標 | 形式 | 時程 |
|-------|------|------|------|
| Phase 1 | 驗證核心管道能跑通 | CLI tool | 3 天 |
| Phase 2 | 使用者測試、收集回饋 | Streamlit Web UI | 5 天 |
| Phase 3 | 產品化、擴大使用者群 | Tauri desktop app | PMF 驗證後 |

---

## 2. Architecture

### 2.1 High-level architecture

```
┌──────────────────────────────────────────────────┐
│                  SnapScript                      │
│                                                  │
│  ┌───────────┐   ┌──────────┐   ┌──────────────┐ │
│  │ Interface │──▶│  Core    │──▶│   Sandbox    │ │
│  │  Layer    │   │  Engine  │   │   Executor   │ │
│  │           │◀──│          │◀──│              │ │
│  └───────────┘   └──────────┘   └──────────────┘ │
│   Phase 1: CLI        │                │         │
│   Phase 2: Web        │                │         │
│                       ▼                ▼         │
│                 ┌──────────┐   ┌──────────────┐  │
│                 │ Claude   │   │ Local        │  │
│                 │ API      │   │ Filesystem   │  │
│                 └──────────┘   └──────────────┘  │
└──────────────────────────────────────────────────┘
```

### 2.2 Layer responsibilities

**Interface Layer**：負責接收使用者輸入（自然語言 + 檔案路徑）與呈現輸出（結果預覽、生成的程式碼、錯誤訊息）。Phase 1 為 CLI（argparse），Phase 2 為 Streamlit Web UI。

**Core Engine**：系統的大腦。負責 (1) 解析輸入檔案的 schema，(2) 組裝 prompt 並呼叫 Claude API 生成腳本，(3) 對生成的腳本做安全檢查，(4) 處理 error retry loop。此層不依賴任何特定的 Interface 或 Sandbox 實作。

**Sandbox Executor**：負責在隔離環境中執行生成的 Python 腳本並捕獲結果（stdout、stderr、輸出檔案）。Phase 1 使用 subprocess，Phase 3 升級為 Docker。

### 2.3 Design principles

- **Interface-agnostic core**：Core Engine 透過 function call 暴露能力，不依賴 CLI 或 Web 框架。新增 Interface（如 Tauri、Slack bot）只需寫一個薄 adapter。
- **Fail-safe execution**：所有使用者提供的檔案以唯讀方式掛載；輸出寫到獨立的 temp 目錄；超時自動終止。
- **Progressive disclosure**：預設只展示結果；使用者可選擇檢視生成的程式碼和執行 log。

---

## 3. Module specifications

### 3.1 Module: `schema_inspector`

**Purpose**：讀取輸入檔案，提取 schema 資訊供 LLM 使用，避免在 prompt 中塞入整個檔案內容。

**Input**：檔案路徑（str）

**Output**：`SchemaReport` dataclass

```python
@dataclass
class SchemaReport:
    filename: str
    file_type: str            # "csv" | "excel"
    row_count: int
    columns: list[ColumnInfo]
    sample_rows: list[dict]   # 前 5 行的資料（用於 few-shot）
    file_size_bytes: int
    encoding: str             # 偵測到的編碼（如 utf-8, big5）
    sheet_names: list[str]    # Excel 專用，CSV 為空

@dataclass
class ColumnInfo:
    name: str
    dtype: str                # "int64", "float64", "object", "datetime64" 等
    null_count: int
    unique_count: int
    sample_values: list[str]  # 前 3 個非空值
```

**Implementation notes**：
- 使用 `pandas.read_csv()` / `pandas.read_excel()` 讀取，但只讀取前 1000 行來做 schema 推斷（大檔案不要全讀）。
- 編碼偵測使用 `chardet` 或 `charset-normalizer`，偵測失敗時 fallback 到 utf-8。
- Excel 多 sheet 時，預設讀取第一個 sheet，但在 SchemaReport 中列出所有 sheet 名稱讓使用者選擇。
- 檔案大小超過 500MB 時拒絕處理並提示使用者。

---

### 3.2 Module: `prompt_builder`

**Purpose**：將使用者的自然語言描述 + SchemaReport 組裝成結構化的 prompt，發送給 Claude API。

**Prompt template structure**：

```
System prompt:
  你是一個 Python 資料處理腳本生成器。
  你只能使用以下 library：pandas, openpyxl, csv, json, re, datetime, pathlib。
  你必須遵守以下規則：
  1. 讀取路徑固定為 INPUT_PATH（由呼叫方注入）。
  2. 輸出路徑固定為 OUTPUT_PATH（由呼叫方注入）。
  3. 不得使用 os.system(), subprocess, exec, eval, __import__。
  4. 不得進行任何網路請求。
  5. 結果必須寫入 OUTPUT_PATH，並在 stdout 印出摘要。
  6. 加入 try/except 包裹主邏輯，stderr 印出錯誤細節。
  7. 只輸出 Python code，不要 markdown 包裹，不要解釋文字。

User prompt:
  ## 輸入檔案資訊
  - 檔名：{filename}
  - 類型：{file_type}
  - 行數：{row_count}
  - 欄位：
    {columns 的格式化列表，含 dtype 和 sample_values}

  ## 範例資料（前 5 行）
  {sample_rows 的 markdown 表格}

  ## 任務描述
  {使用者的自然語言輸入}

  ## 輸出要求
  將結果儲存到 OUTPUT_PATH，格式為 {推斷的輸出格式}。
  在 stdout 印出處理摘要（處理了幾行、移除了幾行等）。
```

**Implementation notes**：
- `INPUT_PATH` 和 `OUTPUT_PATH` 作為 placeholder 寫進 prompt，在實際執行時由 Sandbox Executor 替換為真實路徑。
- 輸出格式的推斷邏輯：輸入是 CSV → 輸出 CSV；輸入是 Excel → 輸出 Excel；使用者在描述中指定了格式則以使用者為準。
- Token 預算控制：如果 schema + sample 超過 2000 tokens，truncate sample_rows 到 3 行，再不夠就移除 sample_values。

---

### 3.3 Module: `code_generator`

**Purpose**：呼叫 Claude API，取得生成的 Python 腳本，並做後處理。

**Input**：組裝好的 prompt（from prompt_builder）

**Output**：`GeneratedScript` dataclass

```python
@dataclass
class GeneratedScript:
    code: str                 # 清洗後的 Python code
    raw_response: str         # Claude 原始回傳（debug 用）
    model: str                # 使用的 model name
    input_tokens: int
    output_tokens: int
```

**API call configuration**：

```python
CLAUDE_CONFIG = {
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 4096,
    "temperature": 0,          # 程式碼生成需要確定性
}
```

**Post-processing pipeline**：
1. Strip markdown code fences（如果 Claude 不小心包了 ```python ... ```）。
2. 移除任何非 Python code 的前後文字說明。
3. 驗證生成的 code 是合法 Python（`ast.parse()`）。
4. 注入 INPUT_PATH / OUTPUT_PATH 的實際值（`str.replace()`）。

**為什麼用 Sonnet 而非 Opus**：資料處理腳本的複雜度通常不高，Sonnet 的程式碼品質已足夠，且 token 成本低 5-10x，對需要 retry 的場景更友善。如果 Sonnet 連續失敗 2 次，可以 fallback 到 Opus。

---

### 3.4 Module: `safety_checker`

**Purpose**：在執行前對生成的 Python 腳本做靜態安全分析，攔截危險操作。

**Implementation**：使用 Python `ast` module 走訪 AST，檢查以下規則：

```python
BLOCKED_IMPORTS = {
    "os", "sys", "subprocess", "shutil", "socket",
    "http", "urllib", "requests", "ftplib", "smtplib",
    "pickle", "shelve", "ctypes", "importlib",
    "code", "codeop", "compile", "compileall",
}

BLOCKED_CALLS = {
    "exec", "eval", "compile", "__import__",
    "globals", "locals", "getattr", "setattr", "delattr",
    "open",  # 只允許透過 pandas 讀寫，不允許直接 open()
}

BLOCKED_ATTRIBUTES = {
    "os.system", "os.popen", "os.exec*",
    "subprocess.run", "subprocess.Popen",
}
```

**檢查流程**：
1. `ast.parse(code)` — 如果 parse 失敗，直接拒絕。
2. Walk AST nodes，檢查 `Import` / `ImportFrom` 是否在 BLOCKED_IMPORTS 中。
3. 檢查 `Call` nodes 的函數名是否在 BLOCKED_CALLS 中。
4. 檢查 `Attribute` access 是否匹配 BLOCKED_ATTRIBUTES。
5. 檢查是否有 `open()` 呼叫——僅允許 pandas 的讀寫方法。

**Output**：`SafetyResult`

```python
@dataclass
class SafetyResult:
    is_safe: bool
    violations: list[str]     # 人類可讀的違規描述
    ast_valid: bool
```

**注意**：靜態分析無法攔截所有攻擊（如動態字串拼接的 import）。此模組是第一道防線，Sandbox Executor 的資源限制是第二道。

---

### 3.5 Module: `sandbox_executor`

**Purpose**：在受限環境中執行 Python 腳本並捕獲所有輸出。

**Phase 1 實作（subprocess）**：

```python
EXECUTION_CONFIG = {
    "timeout_seconds": 30,
    "max_output_size_bytes": 10 * 1024 * 1024,  # 10MB
    "python_executable": "python3",
}
```

**執行流程**：
1. 建立 temp directory 作為工作區（`tempfile.mkdtemp()`）。
2. 將輸入檔案 **複製** 到工作區（不要讓腳本存取原始路徑）。
3. 將生成的腳本寫入工作區的 `script.py`。
4. 用 `subprocess.run()` 執行，設定 `timeout`、`cwd` 為工作區。
5. 捕獲 stdout 和 stderr。
6. 檢查工作區是否產生了輸出檔案。
7. 清理工作區（除了輸出檔案）。

**Output**：`ExecutionResult`

```python
@dataclass
class ExecutionResult:
    success: bool
    stdout: str
    stderr: str
    output_files: list[str]   # 輸出檔案的路徑列表
    execution_time_seconds: float
    exit_code: int
```

**Phase 3 升級（Docker）**：

```python
DOCKER_CONFIG = {
    "image": "python:3.12-slim",
    "network": "none",
    "memory": "512m",
    "cpu_period": 100000,
    "cpu_quota": 50000,       # 50% of 1 core
    "read_only": True,
    "tmpfs": {"/tmp": "size=100m"},
    "volumes": {
        "{input_dir}": {"bind": "/data/input", "mode": "ro"},
        "{output_dir}": {"bind": "/data/output", "mode": "rw"},
    },
}
```

---

### 3.6 Module: `retry_handler`

**Purpose**：當腳本執行失敗時，將錯誤訊息回饋給 Claude，要求修正程式碼。

**Retry strategy**：

```
Max retries: 2（即最多執行 3 次：1 次原始 + 2 次修正）

Retry prompt template:
  你先前生成的腳本執行失敗。
  ## 錯誤訊息
  {stderr}

  ## 先前生成的腳本
  {previous_code}

  請修正腳本。只輸出完整的修正後 Python code。
```

**Retry 決策邏輯**：
- `exit_code != 0` 且 `stderr` 包含 Python traceback → 觸發 retry。
- `timeout` → 不 retry（通常是邏輯問題，不是 bug）。
- `safety_checker` 攔截 → 不 retry（重新生成也可能繼續違規）。
- retry 次數耗盡 → 向使用者展示錯誤訊息和生成的程式碼，建議修改描述後重試。

**Model escalation**：
- 前 2 次使用 Sonnet。
- 如果 Sonnet 連續 2 次失敗，第 3 次（最後一次）自動升級為 Opus。

---

### 3.7 Module: `cli_interface`（Phase 1）

**Purpose**：命令列介面。

**Usage**：

```bash
# 基本用法
snapscript "去除 email 欄位重複的行，保留最新一筆" --file data.csv

# 指定輸出路徑
snapscript "篩選出金額大於 1000 的訂單" --file orders.xlsx --output filtered.xlsx

# 指定 Excel sheet
snapscript "計算每個部門的平均薪資" --file hr.xlsx --sheet "2024Q1"

# 顯示生成的程式碼但不執行
snapscript "合併所有 email 欄位" --file contacts.csv --dry-run

# 跳過確認直接執行
snapscript "轉換日期格式為 YYYY-MM-DD" --file log.csv --yes
```

**CLI arguments**：

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `task` | positional str | Yes | — | 自然語言任務描述 |
| `--file`, `-f` | str | Yes | — | 輸入檔案路徑 |
| `--output`, `-o` | str | No | `{原檔名}_output.{ext}` | 輸出檔案路徑 |
| `--sheet`, `-s` | str | No | 第一個 sheet | Excel sheet 名稱 |
| `--dry-run` | flag | No | False | 只生成程式碼，不執行 |
| `--yes`, `-y` | flag | No | False | 跳過確認步驟 |
| `--show-code` | flag | No | False | 執行後顯示完整程式碼 |
| `--api-key` | str | No | env `ANTHROPIC_API_KEY` | Claude API key |
| `--verbose`, `-v` | flag | No | False | 顯示詳細 log |

**CLI output flow**：

```
$ snapscript "去除 email 重複的行，保留最新一筆" -f customers.csv

📂 Reading customers.csv...
   → 45,230 rows × 8 columns
   → Columns: id, name, email, phone, created_at, ...

🤖 Generating script...
   → Model: claude-sonnet-4, tokens: 847 in / 312 out

🔍 Safety check passed.

⚡ Execute? (Y/n/show code): y

⏳ Running... (2.1s)

✅ Done!
   → Removed 3,847 duplicate rows
   → Output: customers_output.csv (41,383 rows)
```

---

### 3.8 Module: `web_interface`（Phase 2）

**Purpose**：Streamlit Web UI，支援拖拉檔案和即時預覽。

**Page layout**：

```
┌──────────────────────────────────────────────┐
│  SnapScript                    [API Key: •••] │
├──────────────────────────────────────────────┤
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │  📂 Drag & drop CSV/Excel here        │  │
│  │     or click to browse                │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  📋 File preview (first 10 rows)            │
│  ┌────────────────────────────────────────┐  │
│  │  id | name    | email        | amount  │  │
│  │  1  | Alice   | a@test.com   | 500     │  │
│  │  2  | Bob     | b@test.com   | 1200    │  │
│  │  ...                                   │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  Column info:                                │
│  • id (int64) — 5000 unique                 │
│  • name (object) — 4832 unique, 12 nulls    │
│  • email (object) — 4756 unique, 0 nulls    │
│  • amount (float64) — range: 0.5 ~ 99999.0 │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │  Describe your task...                 │  │
│  │  e.g. "Remove rows where amount < 100" │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  [▶ Generate & Run]                          │
│                                              │
│  ─── Results ───────────────────────────────│
│                                              │
│  ✅ Processed 5,000 → 3,847 rows (2.3s)     │
│                                              │
│  📋 Output preview (first 10 rows)          │
│  ┌────────────────────────────────────────┐  │
│  │  id | name    | email        | amount  │  │
│  │  3  | Carol   | c@test.com   | 2400    │  │
│  │  ...                                   │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  [📥 Download result]  [👁 View code]        │
│                                              │
└──────────────────────────────────────────────┘
```

**Streamlit components mapping**：

| UI Element | Streamlit Component |
|------------|-------------------|
| 檔案上傳 | `st.file_uploader(type=["csv","xlsx","xls"])` |
| 檔案預覽 | `st.dataframe()` (read-only) |
| 欄位資訊 | `st.expander()` + `st.markdown()` |
| 任務描述 | `st.text_area()` |
| 執行按鈕 | `st.button()` |
| 進度顯示 | `st.status()` |
| 結果預覽 | `st.dataframe()` |
| 下載結果 | `st.download_button()` |
| 檢視程式碼 | `st.expander()` + `st.code()` |
| API Key | `st.sidebar` + `st.text_input(type="password")` |
| Sheet 選擇 | `st.selectbox()`（僅 Excel 時顯示） |

**State management**：
使用 `st.session_state` 管理以下狀態：
- `uploaded_file`：上傳的檔案物件
- `schema_report`：SchemaReport
- `generated_code`：GeneratedScript
- `execution_result`：ExecutionResult
- `retry_count`：當前 retry 次數

---

## 4. Data flow

### 4.1 Happy path（成功路徑）

```
User Input
  │
  ▼
schema_inspector.inspect(file_path)
  │ → SchemaReport
  ▼
prompt_builder.build(task_description, schema_report)
  │ → formatted prompt (system + user)
  ▼
code_generator.generate(prompt)
  │ → GeneratedScript
  ▼
safety_checker.check(generated_script.code)
  │ → SafetyResult (is_safe=True)
  ▼
[Interface asks user to confirm — unless --yes flag]
  │
  ▼
sandbox_executor.execute(generated_script.code, input_file, output_path)
  │ → ExecutionResult (success=True)
  ▼
Interface displays results + offers download
```

### 4.2 Error retry path

```
sandbox_executor.execute(...)
  │ → ExecutionResult (success=False, stderr="KeyError: 'emal'")
  ▼
retry_handler.should_retry(execution_result, attempt=1)
  │ → True
  ▼
retry_handler.build_retry_prompt(execution_result, previous_code)
  │ → retry prompt
  ▼
code_generator.generate(retry_prompt)
  │ → new GeneratedScript
  ▼
safety_checker.check(...)
  │ → SafetyResult (is_safe=True)
  ▼
sandbox_executor.execute(new_code, ...)
  │ → ExecutionResult (success=True)
  ▼
Interface displays results
```

### 4.3 Safety violation path

```
code_generator.generate(...)
  │ → GeneratedScript (contains "import os")
  ▼
safety_checker.check(...)
  │ → SafetyResult (is_safe=False, violations=["Blocked import: os"])
  ▼
Interface displays:
  "⚠️ Generated code contains unsafe operations. Please rephrase your task."
  [Shows violations list]
  [Does NOT offer retry — regeneration with different prompt is needed]
```

---

## 5. Project structure

```
snapscript/
├── pyproject.toml              # Project metadata, dependencies, CLI entry point
├── README.md
├── .env.example                # ANTHROPIC_API_KEY=sk-ant-...
│
├── src/
│   └── snapscript/
│       ├── __init__.py
│       ├── __main__.py         # python -m snapscript entry point
│       │
│       ├── core/
│       │   ├── __init__.py
│       │   ├── schema_inspector.py
│       │   ├── prompt_builder.py
│       │   ├── code_generator.py
│       │   ├── safety_checker.py
│       │   ├── sandbox_executor.py
│       │   ├── retry_handler.py
│       │   └── models.py       # All dataclasses (SchemaReport, etc.)
│       │
│       ├── interfaces/
│       │   ├── __init__.py
│       │   ├── cli.py          # Phase 1: argparse CLI
│       │   └── web.py          # Phase 2: Streamlit app
│       │
│       ├── prompts/
│       │   ├── system.txt      # System prompt template
│       │   └── retry.txt       # Retry prompt template
│       │
│       └── config.py           # Constants, model config, limits
│
├── tests/
│   ├── test_schema_inspector.py
│   ├── test_prompt_builder.py
│   ├── test_safety_checker.py
│   ├── test_sandbox_executor.py
│   └── fixtures/
│       ├── sample.csv
│       ├── sample.xlsx
│       └── malicious_code.py   # Safety checker test cases
│
└── scripts/
    └── install_sandbox_deps.sh  # 在 Docker image 中預裝 pandas 等
```

---

## 6. Dependencies

### 6.1 Runtime dependencies

```toml
[project]
dependencies = [
    "anthropic>=0.40.0",       # Claude API SDK
    "pandas>=2.2.0",           # CSV/Excel reading, schema inspection
    "openpyxl>=3.1.0",         # Excel (.xlsx) support
    "chardet>=5.0.0",          # File encoding detection
    "rich>=13.0.0",            # CLI pretty printing (Phase 1)
    "streamlit>=1.40.0",       # Web UI (Phase 2)
    "python-dotenv>=1.0.0",    # .env file loading
]

[project.scripts]
snapscript = "snapscript.__main__:main"
```

### 6.2 Development dependencies

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "ruff>=0.8.0",             # Linting & formatting
]
```

### 6.3 Sandbox dependencies（腳本執行環境中需預裝）

```
pandas>=2.2.0
openpyxl>=3.1.0
xlrd>=2.0.0                    # 支援 .xls 格式
```

---

## 7. Configuration

### 7.1 `config.py`

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class AppConfig:
    # Claude API
    default_model: str = "claude-sonnet-4-20250514"
    fallback_model: str = "claude-opus-4-20250514"
    max_tokens: int = 4096
    temperature: float = 0.0

    # Execution
    execution_timeout_seconds: int = 30
    max_retries: int = 2
    max_output_file_size_bytes: int = 100 * 1024 * 1024  # 100MB

    # File handling
    max_input_file_size_bytes: int = 500 * 1024 * 1024   # 500MB
    schema_sample_rows: int = 5
    schema_inspect_rows: int = 1000

    # Safety
    allowed_imports: frozenset = frozenset({
        "pandas", "pd",
        "openpyxl",
        "csv", "json", "re", "datetime", "pathlib",
        "collections", "itertools", "functools",
        "math", "decimal",
        "typing",
    })

    # Prompt
    max_prompt_tokens: int = 8000
```

---

## 8. Error handling strategy

### 8.1 Error categories

| Category | Example | User-facing message | Action |
|----------|---------|-------------------|--------|
| INPUT_ERROR | 檔案不存在、格式不支援 | "Cannot read file: {reason}" | 不呼叫 API |
| API_ERROR | Rate limit, auth fail | "Claude API error: {detail}" | 提示檢查 API key |
| GENERATION_ERROR | Claude 回傳非法 Python | "Failed to generate valid code" | 自動 retry 1 次 |
| SAFETY_ERROR | 生成了危險程式碼 | "Generated code blocked for safety" | 不 retry，要求使用者修改描述 |
| EXECUTION_ERROR | 腳本拋出 exception | "Script failed: {traceback summary}" | 自動 retry（含 error context） |
| TIMEOUT_ERROR | 超過 30 秒 | "Script timed out (>30s)" | 不 retry |

### 8.2 Logging

- Phase 1 使用 Python `logging` module，輸出到 stderr。
- 記錄每次 API call 的 model、token count、latency。
- 記錄每次 execution 的 duration、exit code。
- **不記錄**使用者的檔案內容或完整的 API prompt（隱私考量）。

---

## 9. Security model

### 9.1 Threat model

| Threat | Mitigation |
|--------|-----------|
| LLM 生成刪除系統檔案的程式碼 | safety_checker 靜態分析 + sandbox 只能存取工作區 |
| LLM 生成外傳使用者資料的程式碼 | safety_checker 攔截網路相關 import + Phase 3 Docker `--network=none` |
| 使用者上傳惡意檔案（如 zip bomb） | 檔案大小限制 500MB + schema_inspector 只讀前 1000 行 |
| 腳本無限迴圈耗盡資源 | subprocess timeout 30s + Phase 3 Docker memory limit |
| Prompt injection via 檔案內容 | Schema inspector 只傳 column names + sample values，不傳完整內容 |

### 9.2 Phase 1 vs Phase 3 security comparison

| 維度 | Phase 1 (subprocess) | Phase 3 (Docker) |
|------|---------------------|-----------------|
| Process 隔離 | 同一 user 的子進程 | 獨立 container |
| 網路存取 | 可存取（靠 safety_checker 攔截） | `--network=none` 完全阻斷 |
| 檔案系統 | 可存取 temp dir 以外的檔案（靠 safety_checker 攔截） | `--read-only` + 僅掛載 input/output |
| 資源限制 | 僅 timeout | CPU、memory、disk 全限制 |
| 適用場景 | 本地開發 & 測試 | 任何生產環境 |

---

## 10. Testing strategy

### 10.1 Unit tests

- `test_schema_inspector.py`：各種 CSV/Excel 的 schema 提取（含 encoding 偵測、缺失值、多 sheet）。
- `test_safety_checker.py`：已知的危險程式碼 pattern 全部能攔截；合法程式碼不會誤判。
- `test_prompt_builder.py`：不同 schema 組合的 prompt 格式正確、token 不超限。
- `test_sandbox_executor.py`：正常執行、timeout、stderr 的捕獲。

### 10.2 Integration tests

- End-to-end happy path：給定一個 CSV + 任務描述 → 呼叫真實 Claude API → 執行 → 驗證輸出檔案正確。
- Error retry path：故意提供會導致 KeyError 的任務描述 → 驗證 retry 能修正。

### 10.3 Test fixtures

在 `tests/fixtures/` 準備：
- `sample.csv`：100 行，含常見的 dirty data（重複、空值、格式不一致）。
- `sample.xlsx`：多 sheet，含日期欄位和數值欄位。
- `big5_encoded.csv`：Big5 編碼的中文 CSV。
- `malicious_code.py`：包含各種危險 pattern 的 Python 檔案。

---

## 11. Future considerations（Phase 3+）

### 11.1 Tauri 整合

Phase 3 前端使用 React + Tauri，Python 後端以 FastAPI 形式運行於 `localhost`，Tauri Rust 端負責啟動/關閉 Python 進程。詳細架構另行撰寫。

### 11.2 Potential feature extensions

- **多檔案操作**：支援 "merge A.csv and B.csv on email column" 類型的任務。
- **常用任務模板**：根據使用者歷史，推薦 "Remove duplicates"、"Format dates" 等常用操作。
- **資料視覺化**：生成 matplotlib 圖表並預覽。
- **批次模式**：一次對多個檔案套用同一個操作。
- **Slack / Discord bot**：`@snapscript [attached file] 去重` 直接在聊天中完成。

### 11.3 Monetization

| Tier | Price | Limits |
|------|-------|--------|
| Free | $0 | 5 executions/day, user's own API key |
| Pro | $9.99/mo | Unlimited, built-in API key, execution history, priority retry |
| Team | $29.99/mo/seat | Shared templates, audit log, SSO |
