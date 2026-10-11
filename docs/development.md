# SnapScript Development Guide

更新：2026-10-10。本文件整併 Phase 1、2、3、4A、4B 的規劃與共用驗收清單，取代原本七份 Phase 文件。階段狀態依目前程式與已記錄的驗收結果整理。

## 文件入口

| 文件 | 用途 |
| --- | --- |
| [README](../README.md) | 安裝、CLI、Streamlit 與設定 |
| 本文件 | 開發流程、架構、Phase 1–4 與 Agent/MCP 使用方式 |
| [AGENTS.md](../AGENTS.md) / [CLAUDE.md](../CLAUDE.md) | 開發 Agent 的工作規則 |
| [spec.md](../spec.md) | 當前 AI CSV Merge 功能規格與驗收條件 |
| [MCP spec](../specs/mcp.md) | 本機 MCP 的工具契約、驗收條件與實際結果 |
| [CSV Merge 驗收報告](ai_csv_merge_verification.md) | 實際測試結果與涵蓋範圍 |
| [Docker sandbox](docker_sandbox.md) | 映像建置、隔離設定與故障排除 |

## Spec-driven development

Codex／Claude Code 擔任開發 Agent，依規格修改 SnapScript：

1. 讀取 `AGENTS.md`、本文件與對應功能 spec（CSV Merge：`spec.md`；MCP：`specs/mcp.md`），先查看 `git status --short`。
2. 對照現有實作，補齊合併規則、限制、錯誤與可重現的預期結果。
3. 在 spec 保留短工作清單；只修改需求缺口，沿用既有 core。
4. 加入有意義的回歸測試，先跑相關測試，修正失敗後再跑完整驗收。
5. 將各項 AC 的結果、指令與限制寫入驗收報告；外部測試未執行時標記未驗證。

可直接交給開發 Agent 的指令：

```text
閱讀 AGENTS.md、docs/development.md 與 spec.md。
對照現有程式，只實作規格缺口；補測試、修正失敗、執行驗收，
更新 docs/ai_csv_merge_verification.md。沿用現有授權處理例行決策。
不要 commit 或 push。
```

這套流程由開發 Agent 執行；SnapScript 執行資料處理時仍使用下列 core pipeline。

## Architecture

```text
CLI / Streamlit / MCP
  -> schema_inspector.inspect / inspect_many
  -> prompt_builder.build / build_many
  -> retry_handler.run / run_many
      -> code_generator.generate
      -> safety_checker.check
      -> execution_backend.execute
          -> subprocess / Docker
          -> output validation and copy-out
```

- `src/snapscript/core/` 負責資料、prompt、provider、AST、重試與執行；不依賴 UI。
- `src/snapscript/interfaces/` 收集輸入、呼叫 core、顯示結果；不重做轉換邏輯。
- 共用 dataclass 放在 `core/models.py`；core 使用 typed exception，介面格式化錯誤。
- Provider/model 由 `AppConfig` 決定，SDK 細節留在 provider wrapper；重試最多三次模型呼叫。
- 所有生成程式先過 AST，再經 sandbox；介面不直接執行生成程式。
- `_snapscript_paths.py` 提供 `INPUT_PATH`／`INPUT_PATHS` 與 `OUTPUT_PATH`。不替換程式字串，也不把真實來源路徑放進 prompt。
- 輸入複製進每次執行的 workspace；拒絕覆蓋來源的輸出路徑，以及 symlink／非一般檔案輸出。輸出須可讀且有資料列。
- Audit 是本機、best-effort、預設 metadata/hash；不預設記錄資料內容、完整 prompt/code、金鑰或 traceback。

## Phase summary

目前開發重點仍為 **Phase 4A**。以下區分程式已存在與尚未完成的整合／手動驗收。

| 階段 | 範圍 | 目前狀態 |
| --- | --- | --- |
| Phase 1（Tasks 1–20） | 單檔 CLI 與安全 core pipeline | 已實作；保留既有 CLI 行為 |
| Phase 2（Tasks 21–31） | Streamlit、session state、限流、audit | 已實作；舊手動驗收清單未記錄完成 |
| Phase 3A（Tasks 32–36、42） | Docker backend、映像、隔離、router | 已實作；CSV Merge 真實 Docker gate 已通過 |
| Phase 3B（Tasks 37–39） | JSON command adapter、Tauri | 延後，尚未實作 |
| Phase 3C（Tasks 40–41） | 本機 stdio MCP server | 已依使用者要求實作；兩個工具與驗收結果見 MCP spec |
| Phase 4A（Tasks 43–50） | 最多兩個具名 CSV/XLSX 輸入 | 已實作；既有 gate 與 CSV Merge 驗收已通過 |
| Phase 4B（Tasks 51–57） | Prompt Coach、AI task rewrite | Core/UI 與自動測試已存在；未找到完成手動 gate 的紀錄 |

### Phase 1 — CLI / Core

- 支援單一 `.csv`／`.xlsx`、schema inspection、prompt、生成、AST、sandbox、輸出檢查與 bounded retry。
- CLI 保留 `--file`、`--output`、`--sheet`、`--dry-run`、`--show-code`、`--model`、`--yes` 等選項；dry-run 會呼叫 provider，但不執行生成程式。
- 原始 prompt 品質 gate：十個固定 CLI 任務至少八個在第一次生成成功，不能用重試通過取代此門檻。歷史迭代記錄見 [Prompt Changelog](../src/snapscript/prompts/CHANGELOG.md)。

### Phase 2 — Streamlit

- 根目錄 `app.py` 是入口，UI 位於 `interfaces/web.py`；Generate 才執行轉換 pipeline。
- 上傳上限 10 MiB，預覽最多 100 列；每個 session 最多十次 Generate、冷卻五秒。
- 更新輸入或開始新 run 時處理舊結果；失敗不提供 stale preview/download，錯誤須遮罩並限制長度。
- Audit 使用本機 JSONL，寫入失敗不影響資料處理；正常 pytest 不呼叫真實 provider。
- Generate 共用一條執行／錯誤流程，每次接受的執行只寫一筆 audit；UI 與 audit 共用敏感資訊遮罩。Audit 僅記錄已有資料，不預留 generated-code hash 或 attempt count；雙檔不填入單檔 size/hash，也不以空檔案代替。

### Phase 3 — Sandbox / Future interfaces

- 預設 backend 仍為 subprocess；需要主機檔案隔離時明確設定 `SNAPSCRIPT_SANDBOX_BACKEND=docker`。
- Docker 只掛載每次的 workspace，保留非 root、記憶體／CPU／PID 限制，網路必須關閉，不自動退回 subprocess。
- 每次 Docker execution 最多三十秒，含啟動，不含 provider 呼叫或輸入準備；超時不重試，另以五秒期限 force-remove 該容器後清理 workspace，清理失敗須回報。
- MCP 已加入本機 stdio 薄介面，沿用 core；轉換固定使用 Docker。Tauri 與其 JSON adapter 尚未加入。
- Docker 操作細節統一維護在 [docker_sandbox.md](docker_sandbox.md)。

### Phase 4A — Named two-file inputs

- 支援最多兩個具名輸入，例如 `orders=orders.csv`、`products=products.xlsx`；單檔 `--file input.csv` 保持相容。
- 共用 `InputFileSpec`、`NamedSchemaReport`、`MultiFileSchemaReport`；多檔生成程式使用 `INPUT_PATHS` 與 `OUTPUT_PATH`。
- LLM 解讀使用者的 join/merge 任務；SnapScript 提供 schema、路徑、安全檢查與輸出驗證，不自行解析自然語言 join 指令。
- CSV Merge 的鍵、join、重複鍵、型別、空結果與錯誤規則以 [spec.md](../spec.md) 為準。
- 歷史 gate（2026-05-26）：一般與無金鑰 pytest 各 339 passed、CLI help 通過、多檔 join integration 兩項通過；當時 Docker／真實 provider 未執行。
- 最新 CSV Merge gate（2026-10-10）與真實 Claude/Docker 證據見 [驗收報告](ai_csv_merge_verification.md)。舊 gate 的結果不代表重新驗證目前版本。

### Phase 4B — Prompt assistance

- `task_advisor.advise_task` 提供本機、非阻擋的建議；不呼叫 provider、不偷偷改寫任務。
- `task_rewriter.rewrite_task` 只在明確點擊 AI Rewrite 後改寫任務文字；使用者檢視／套用後才另外點 Generate。
- Rewrite 不產生 pandas 程式、不執行 sandbox、不建立輸出；不沿用 Generate 的計數器。
- Rewrite 檢查空白、程式碼與實際路徑；不以英文句型猜測欄位並阻擋改寫。來源欄位由 schema 提供，使用者要求的新輸出欄位可保留；改寫文字經使用者檢視，Generate 仍執行完整安全 pipeline。
- Rewrite 限制獨立為每個 session 十次、冷卻三秒；audit 與錯誤沿用安全規則。

## Agent usage and MCP

### 透過 CLI 使用工具

Claude Code 等具備終端機能力的 Agent 可以呼叫 CLI。先依 [Docker 指南](docker_sandbox.md) 建置 sandbox 映像，將範例輸入放在 repo 根目錄，再執行：

```bash
SNAPSCRIPT_SANDBOX_BACKEND=docker uv run --env-file .env python -m snapscript \
  "Merge orders and products on pid with an inner join." \
  --file orders=orders.csv \
  --file products=products.csv \
  --output merged.csv \
  --yes
```

Agent 可讀取 exit code、錯誤訊息與輸出檔。CLI 目前不是 JSON/MCP 介面；Python 呼叫者也可使用上述 core API。CLI 的 `.env` 需由 `uv run --env-file .env` 載入，或預先設定 shell 環境變數。

### 透過 MCP 使用工具

`interfaces/mcp_server.py` 使用官方 [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/) 提供本機 stdio 介面，只註冊兩個工具。外部 Agent 負責讀資料任務 spec、規劃與驗收；SnapScript 負責安全轉換。工具契約與測試證據見 [MCP spec](../specs/mcp.md)。

| MCP tool | 參數與沿用的 core | 回傳 |
| --- | --- | --- |
| `inspect_file_schema` | `files`；呼叫 `inspect_many` | 具名 filename、row count、size、encoding、sheets、欄位與 dtype；最多 100 欄並標記截斷；不回傳樣本值 |
| `transform_files` | `files`、`task`、`output_path`；inspect → build → `run_many` | success、輸出絕對路徑／大小、execution time、Docker backend |

兩者接受一或兩份 CSV/XLSX；`files` 是 logical name 到路徑的 mapping，XLSX 使用第一個工作表。路徑須位於 `--workspace`，可用相對路徑或其內的絕對路徑。拒絕 `..`、解析後越界的 symlink，以及 symlink 輸出。輸出限新 CSV/XLSX 檔案，父目錄須已存在；既有輸出與來源都不覆蓋。

檢查 schema 不需 API key／Docker；轉換需要已設定的 Claude key、Docker daemon 與 [sandbox 映像](docker_sandbox.md#build)。MCP 固定 Docker／禁網，不受 subprocess 或開網設定影響，不退回 subprocess。三十秒限制為每次容器執行，API 呼叫與最多三次生成另計。失敗回傳 MCP `isError` 與最長 1000 字元的遮罩訊息，不回傳 stdout、完整 traceback、程式碼或 prompt。

先建立資料目錄，放入輸入檔案；CLI 的 stdio 啟動指令為：

```bash
mkdir -p data
uv run --env-file .env python -m snapscript.interfaces.mcp_server --workspace ./data
```

stdio 程序等待 MCP client 的 stdin/stdout 訊息；直接執行時保持等待是正常狀態。Claude Code 可依 [官方文件](https://code.claude.com/docs/en/mcp#option-3-add-a-local-stdio-server) 註冊，請將兩個絕對路徑改為你的專案與資料目錄：

```bash
claude mcp add --transport stdio snapscript -- \
  uv --directory /Users/zhenting/SnapScript run --env-file .env \
  python -m snapscript.interfaces.mcp_server \
  --workspace /Users/zhenting/SnapScript/data
```

`inspect_file_schema` 的工具參數範例：

```json
{"files": {"orders": "orders.csv", "products": "products.csv"}}
```

`transform_files` 的工具參數範例：

```json
{
  "files": {"orders": "orders.csv", "products": "products.csv"},
  "task": "Merge orders and products on pid with an inner join.",
  "output_path": "merged.csv"
}
```

使用者可以提供 `tasks/merge_orders.md`，也可讓外部 Agent 先整理需求。給 Agent 的最小指令：

```text
讀取資料任務 spec，確認輸入、處理需求、預期資料與來源保留條件。
呼叫 inspect_file_schema 查看欄位，再以相同 logical names 呼叫 transform_files。
讀取回傳的 output_path，對照預期欄位、完整資料與來源內容，回報各項驗收結果。
```

## Verification

Streamlit 測試共用 `tests/helpers/streamlit_helpers.py` 的假 UI 與 audit fixture。
CLI gate 的 fixture 只保留 10 份輸入 CSV 與 `FIXTURE_MANIFEST.json`；
預期結果直接由測試斷言，不另外保存重複的 expected CSV 或 manifest 文件。

一般 gate（不需要 provider 金鑰或 Docker）：

```bash
uv run pytest
env -u ANTHROPIC_API_KEY uv run pytest
uv run python main.py --help
uv run pytest tests/integration/test_csv_merge_spec.py
uv run pytest tests/test_mcp_server.py
```

明確 opt-in 的外部 gate：

```bash
SNAPSCRIPT_DOCKER_TESTS=1 uv run pytest tests/integration/test_csv_merge_docker.py
SNAPSCRIPT_REAL_PROVIDER=1 uv run --env-file .env pytest tests/integration/test_csv_merge_real_provider.py
SNAPSCRIPT_REAL_PROVIDER=1 uv run --env-file .env pytest tests/integration/test_cli_gate_tasks.py
SNAPSCRIPT_DOCKER_TESTS=1 uv run pytest tests/integration/test_mcp_pipeline.py
SNAPSCRIPT_DOCKER_TESTS=1 SNAPSCRIPT_REAL_PROVIDER=1 uv run --env-file .env pytest tests/integration/test_mcp_pipeline.py
```

Streamlit 手動 gate 尚需逐項記錄結果；原清單沒有完成紀錄：

- [ ] 啟動 `uv run --env-file .env streamlit run app.py`；上傳 CSV/XLSX，確認 `.xls`、錯誤格式與超大檔案被拒絕。
- [ ] 沒有檔案／空白任務時阻擋 Generate；上傳與修改文字不啟動 provider。
- [ ] 使用 `task_02_orders.csv` 執行 `amount > 1000` 任務，核對 preview 與下載檔；失敗或更換輸入時不顯示舊結果。
- [ ] 核對 Generate 十次／五秒、Rewrite 十次／三秒限制；被阻擋的點擊不計數、不呼叫 provider。
- [ ] 核對 Prompt Coach 不阻擋 Generate；AI Rewrite 只提供待檢視的文字，不自動產生結果。
- [ ] 驗證 provider／AST／sandbox 錯誤、錯誤後重試、session 恢復，以及 error/audit 的遮罩。

## Remaining work

- 完成並記錄上述 Streamlit 手動 gate；不以 mocked UI 測試取代真實操作紀錄。
- 延後的 Tauri 先建立 spec，再加入薄介面與 mock 測試；不要混入 Phase 4A 的資料處理邏輯。
- 無限多檔、資料庫、cloud execution、auth、billing、dashboards、persistent history 不屬於目前範圍。
