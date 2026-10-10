# InsightFlow AI

An evidence-first retail analytics platform. Analysts will import retail data, validate its quality, analyze profitability, investigate business changes, and ask natural-language questions answered with verifiable SQL results.

> **Current status: Phase 2 in progress — CSV ingestion and first analytics.** The backend can accept a CSV upload, validate it, produce a read-only data-quality profile, and calculate basic retail metrics with DuckDB. Files are not stored yet, and there is no upload screen in the UI yet. Profit is intentionally not calculated yet (see below).

## Tech stack

| Layer     | Tools                                          |
| --------- | ---------------------------------------------- |
| Frontend  | React 19, TypeScript, Vite                     |
| Backend   | Python, FastAPI, Pydantic Settings             |
| Analytics | DuckDB (in-memory SQL)                         |
| AI        | Google Gemini behind a provider interface *(later phase)* |
| Testing   | Pytest (backend); oxlint + TypeScript build (frontend) |

## Prerequisites (Windows)

- **Python 3.12+** — check with `py --version`
  (Use `py`, not `python`. On many Windows machines, `python` opens the Microsoft Store.)
- **Node.js 20.19+ or 22.12+** — check with `node --version`
- **Git** — check with `git --version`

## First-time setup

Run these in **PowerShell** from the project root folder (`Insightflow`).

### 1. Backend

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
cd ..
```

After activation your prompt starts with `(.venv)`. Inside the venv, `python` correctly points to the project's Python.

> **"running scripts is disabled on this system"?** Run this once, then try activating again:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

### 2. Frontend

```powershell
cd frontend
npm install
cd ..
```

## Running the app (two terminals)

### Terminal 1 — start the backend

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

Check it directly:
- Health check: <http://127.0.0.1:8000/api/health>
- Interactive API docs: <http://127.0.0.1:8000/docs>

### Terminal 2 — start the frontend

```powershell
cd frontend
npm run dev
```

Open **<http://localhost:5180>**. The **System status** card should show a green dot and **Connected**.

Stop either server with `Ctrl + C`.

## Try the CSV upload endpoint

With the backend running, use either option.

**Option A — in the browser:** open <http://127.0.0.1:8000/docs>, expand **POST /api/uploads/csv**, click **Try it out**, choose a `.csv` file, and click **Execute**.

**Option B — in PowerShell** (from the `backend` folder). Use `curl.exe`, not `curl`: in Windows PowerShell, `curl` is a different command.

```powershell
# Valid file -> 200 with row count and columns
curl.exe -F "file=@tests/fixtures/sample_sales.csv" http://127.0.0.1:8000/api/uploads/csv

# No file -> 400
curl.exe -X POST http://127.0.0.1:8000/api/uploads/csv

# Not a CSV -> 415
curl.exe -F "file=@requirements.txt" http://127.0.0.1:8000/api/uploads/csv
```

| Status | Meaning |
| --- | --- |
| 200 | Valid CSV. Returns `filename`, `size_bytes`, `row_count`, `column_count`, `columns` |
| 400 | No file in the form field named `file` |
| 413 | File is larger than `MAX_UPLOAD_MB` (default 10) |
| 415 | File name doesn't end in `.csv` |
| 422 | It's a `.csv`, but the content is unreadable. The `detail` message says why (e.g. "Line 3 has 1 values, but the header has 2 columns.") |

### Data-quality profile

`POST /api/uploads/csv/profile` accepts the same upload, follows the same status-code rules, and returns a quality report: missing values per column, exact duplicate rows, inferred column types, and type mismatches with line numbers. Each metric's exact definition is included in the response under `definitions`. **The report never changes your data.**

```powershell
# A file with known problems: missing values, a duplicate row, "N/A" in a number column, an impossible date
curl.exe -F "file=@tests/fixtures/messy_sales.csv" http://127.0.0.1:8000/api/uploads/csv/profile
```

### Retail metrics (DuckDB)

`POST /api/uploads/csv/metrics` accepts the same upload, follows the same status-code rules, loads the rows into an in-memory DuckDB database, and calculates the metrics below **only when the needed columns exist**.

| Metric | Needs | Definition |
| --- | --- | --- |
| `row_count` | — | Data rows (header and blank lines not counted). Exact duplicate rows are included and flagged in `notes`. |
| `total_quantity` | `quantity` | Sum of quantity. Negative values (e.g. returns) are included as-is and flagged. |
| `total_revenue` | `revenue`, **or** `quantity` + `unit_price` | Sum of the revenue column as recorded; otherwise the sum of quantity × unit_price (gross sales, before discounts, returns or refunds). The revenue column wins if both exist. |
| `order_count` | `order_id` | Distinct order IDs (exact text). Blank IDs are excluded. |
| `average_order_value` | `order_id` + revenue | Total revenue ÷ distinct orders, using rows that have both an order ID and a usable revenue value. |

**How columns are chosen.** A metric uses a column whose name is *exactly* `order_id`, `quantity`, `unit_price`, or `revenue` (case-sensitive). Nothing is guessed: `Qty` or `Quantity` are not used automatically. If your file uses other names, send them as form fields: `order_id_column`, `quantity_column`, `unit_price_column`, `revenue_column`. The response's `columns_used` shows what was used.

**Every metric reports** `status` (`calculated` or `unavailable`), `value`, `definition`, `columns_used`, `rows_included`, `rows_excluded`, and `notes`. When a metric is unavailable, `notes` explains why.

**Numbers.** A usable number is plain text like `42`, `-3`, or `18.50` (at most 8 decimal places; surrounding spaces ignored). Values like `N/A`, `$5.00`, `1,000`, or `1e3` are **excluded and counted, never treated as zero**, and `notes` lists the line numbers. Math uses exact decimals, so `0.1 + 0.2 = 0.3`.

```powershell
# Columns named exactly order_id, quantity, unit_price
curl.exe -F "file=@tests/fixtures/sample_sales.csv" http://127.0.0.1:8000/api/uploads/csv/metrics

# Your own column names
curl.exe -F "file=@my_sales.csv" -F "order_id_column=OrderNo" -F "quantity_column=Qty" -F "unit_price_column=Price" http://127.0.0.1:8000/api/uploads/csv/metrics

# Blanks, N/A, $, thousands separators, a return: see what gets excluded and why
curl.exe -F "file=@tests/fixtures/numeric_edge_cases.csv" http://127.0.0.1:8000/api/uploads/csv/metrics
```

Naming a column that doesn't exist (or the same column for two roles) returns **422** with the list of available columns.

**Not calculated yet: profit.** It needs a clear data model for cost and agreed definitions for returns and refunds first.

## Running tests and checks

```powershell
# Backend tests
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest -v
cd ..

# Frontend lint + type check + production build
cd frontend
npm run lint
npm run build
cd ..
```

## Troubleshooting

| What you see | Likely cause | Fix |
| --- | --- | --- |
| UI says **Not connected** / "Could not reach the backend (HTTP 502)" | The FastAPI server isn't running | Start Terminal 1, then click **Check again** |
| `Port 5180 is already in use` | Another frontend is still running | Close the other terminal, or stop it with `Ctrl + C` |
| `[Errno 10048] ... address already in use` (backend) | Something else is using port 8000 | Close the old backend terminal |
| `No module named 'app'` | Command run from the wrong folder | `cd backend` first |
| `uvicorn` / `pytest` not recognized | venv not activated | `.\.venv\Scripts\Activate.ps1` |
| Slow installs or "file in use" errors | OneDrive is syncing `node_modules` / `.venv` | Pause OneDrive sync, or move the project to e.g. `C:\dev\Insightflow` |

## Configuration and secrets

- Backend settings live in `backend/.env` (copied from `backend/.env.example`). `.env` is ignored by Git.
- `GEMINI_API_KEY` is read **only by the backend**. Never put API keys in `frontend/`. Anything in frontend code is downloaded by every browser that opens the app.

## Project structure

```
Insightflow/
├─ backend/
│  ├─ app/
│  │  ├─ main.py          # Creates the FastAPI app and registers routes
│  │  ├─ config.py        # Settings loaded from .env (secrets stay here)
│  │  ├─ api/health.py    # GET /api/health
│  │  ├─ api/uploads.py   # POST /api/uploads/csv, /csv/profile, /csv/metrics (request checks only)
│  │  ├─ ingestion/csv_parser.py  # CSV content validation (no FastAPI code)
│  │  ├─ ingestion/profiler.py    # Read-only data-quality report
│  │  ├─ analytics/duckdb_loader.py   # Loads validated rows into in-memory DuckDB, as text
│  │  └─ analytics/retail_metrics.py  # Retail metrics in SQL, only when columns exist
│  ├─ tests/              # one test file per module, plus fixtures/ (sample CSVs)
│  ├─ requirements.txt
│  └─ .env.example
├─ frontend/
│  ├─ src/
│  │  ├─ api/health.ts                # Calls the backend, turns failures into clear messages
│  │  ├─ hooks/useBackendStatus.ts    # Tracks checking / connected / error state
│  │  ├─ components/BackendStatus.tsx # Displays the status card
│  │  ├─ App.tsx                      # Page layout
│  │  └─ index.css                    # Design tokens and styles
│  └─ vite.config.ts                  # Dev server port + /api proxy to the backend
├─ docs/INTERVIEW_NOTES.md
└─ README.md
```

## How it fits together

```
Browser ──► Vite dev server (localhost:5180) ──/api/*──► FastAPI (127.0.0.1:8000)
            serves React UI                  proxy       route handlers → ingestion / analytics modules
```

Separation of responsibilities:

- `backend/app/api/` — thin HTTP routes only (validate input, call a module, return the result)
- `backend/app/ingestion/` — reading, validating, and profiling uploaded files
- `backend/app/analytics/` — DuckDB loading and retail metric SQL, testable without HTTP. Column names from uploaded files never appear in SQL: each column gets a generated identifier (`c0`, `c1`, …), and values are passed as query parameters.
- `backend/app/ai/` — AI provider interface, so Gemini can be swapped or mocked in tests

## Roadmap

1. ✅ Project foundation
2. 🔄 CSV import and data-quality validation (upload, structure check, and quality profile done)
3. 🔄 Retail KPIs (quantity, revenue, orders, AOV done) and profitability analysis
4. Evidence-backed change investigations
5. Natural-language questions answered with verifiable SQL
