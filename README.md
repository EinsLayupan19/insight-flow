# InsightFlow AI

An evidence-first retail analytics platform. Analysts will import retail data, validate its quality, analyze profitability, investigate business changes, and ask natural-language questions answered with verifiable SQL results.

> **Current status: Phase 2 in progress — CSV ingestion and first analytics.** In the browser you can upload a CSV, see why it was rejected (if it was), review a read-only data-quality report, see the basic retail metrics its columns support, and follow **sales trends** (revenue, orders, and average order value by day, week, or month), all calculated with DuckDB. You choose per upload whether the file is **saved to the dataset library** (stored on the server's disk with its analysis history, until you delete it) or **analyzed in memory only** (nothing stored). Profit is intentionally not calculated yet (see [Known limitations](#known-limitations)).

## Tech stack

| Layer     | Tools                                          |
| --------- | ---------------------------------------------- |
| Frontend  | React 19, TypeScript, Vite                     |
| Backend   | Python, FastAPI, Pydantic Settings             |
| Analytics | DuckDB (in-memory SQL)                         |
| Storage   | SQLite (built into Python) for dataset metadata and analysis history; saved CSV files on local disk |
| AI        | Google Gemini behind a provider interface *(later phase)* |
| Testing   | Pytest (backend); Vitest, oxlint, and the TypeScript build (frontend) |

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

## Using the app

1. **Choose a CSV file.** Drag it onto the upload area, or click **Choose a CSV file**. The browser checks the obvious things first (one file, a `.csv` name, not empty) and warns if the file is over the server's default 10 MB limit.
2. **Choose whether to save it.** **Save to the dataset library** is checked by default: the file is stored on the server and every analysis is recorded in its history. Uncheck it to analyze in memory only; then nothing is stored.
3. **Click Save and analyze** (or **Analyze file** when not saving). The server validates the file's structure. If it is rejected, the server's reason is shown (for example "Line 3 has 1 values, but the header has 2 columns.") with **Try again** and **Choose a different file**. A rejected file is never stored.
4. **Review data quality.** Summary tiles (rows, columns, duplicate rows, missing values, type mismatches), the duplicate rows with their line numbers, and a table with each column's inferred type, missing values, mismatched values (with line numbers), and status. The exact definition of every check is under **How these checks are defined**.
5. **Review retail metrics.** Each metric card shows its value, the API's definition, the columns used, how many rows were included and excluded, and any notes. Metrics the file can't support are marked **Unavailable**, with the reason from the API.
6. **Map columns (optional).** If your columns are named differently (for example `Qty` instead of `quantity`), open **Map columns**, pick a column for each role, and click **Apply mapping**. Each column can fill only one role. The mapping applies to the metrics and the sales trends. For a saved file, every mapping you apply is recorded as a new analysis.
7. **Review sales trends.** A column chart of **Gross sales** (or **Revenue (as recorded)**), **Orders**, or **Average order value** per period, with every period in a table below it. Choose **Group by** Day, Week (Monday to Sunday), or Month (the default), and the **Date column** if yours is not named `order_date`. Hover a period, or focus the chart and use the arrow keys, to read its value. Periods with no rows are left empty, never drawn as zero, and rows without a usable date are counted with their line numbers. With many periods (for example two years of days), the chart switches from columns to a line.
8. **Analyze another file** or **Clear results** to start over. The results on this page stay until then (also while you browse saved datasets), but disappear when the page is reloaded. Saved datasets are not affected by clearing.
9. **Browse saved datasets.** Open **Saved datasets** in the header to see every saved file. Open one to see its details (rows, columns, stored-file status, SHA-256), its **analysis history** (newest first), and any recorded result exactly as it was stored. From there you can run a new data-quality check, calculate metrics or trends (with a different column mapping, grain, or date column if needed), or **delete the dataset**, which asks for confirmation first.

**Duplicate uploads.** Saving a file whose content is already in the library (even under another name) does not store a second copy. The page says **Already in the dataset library**, names the existing dataset, and adds the new results to its history.

Sample files to try are in `backend/tests/fixtures/`: `sample_sales.csv` (clean), `messy_sales.csv` (missing values, a duplicate row, `N/A`, an impossible date), `numeric_edge_cases.csv`, `order_lines.csv`, and `no_sales_columns.csv`.

**Endpoints the UI calls** (through the Vite proxy, so the browser only talks to `localhost:5180`):

| Step | Analyze in memory only | Save to the dataset library |
| --- | --- | --- |
| Backend status card | `GET /api/health` | `GET /api/health` |
| Validate | `POST /api/uploads/csv` (file in the form field `file`) | `POST /api/datasets` (stores the file) |
| Data quality | `POST /api/uploads/csv/profile` (uploads the file again) | `POST /api/datasets/{id}/analyses` with `{"kind": "profile"}` |
| Retail metrics | `POST /api/uploads/csv/metrics`, plus `order_id_column`, `quantity_column`, `unit_price_column`, `revenue_column` only for roles you mapped | `POST /api/datasets/{id}/analyses` with `{"kind": "metrics", "column_mapping": {...}}` |
| Sales trends | `POST /api/uploads/csv/trends`, plus `grain`, and `order_date_column` and the other `*_column` fields only for roles you chose | `POST /api/datasets/{id}/analyses` with `{"kind": "trends", "grain": "week", "column_mapping": {...}}` |
| Saved datasets pages | — | `GET /api/datasets`, `GET /api/datasets/{id}`, `GET /api/datasets/{id}/analyses`, `GET /api/datasets/{id}/analyses/{analysis_id}`, `DELETE /api/datasets/{id}` |

Data quality, retail metrics, and sales trends run in parallel after validation succeeds, and each can fail and be retried on its own. Changing the grain or the date column re-runs only the trends.

## Saved datasets: what is stored, and where

Nothing is stored unless you save it. When you do, two things are kept on the machine running the backend, under `DATA_DIR` (default `backend/data/`, which Git ignores):

| What | Where | Details |
| --- | --- | --- |
| The uploaded file, byte for byte | `DATA_DIR/uploads/<sha256>.csv` | Named by the SHA-256 hash of its content. The name you uploaded is only a label in the database and is never used as a path. |
| Dataset metadata and every analysis result | `DATA_DIR/insightflow.db` (SQLite) | `datasets`: name, hash, size, rows, columns, saved time. `analyses`: kind, column mapping, the full result as returned, the InsightFlow version, time. |

- **How long:** until you delete the dataset. Deleting removes the stored file and then the metadata and the whole history (the database deletes a dataset's analyses with it).
- **Not backed up, not synced, not uploaded anywhere else.** Copying `DATA_DIR` is the backup. Deleting `DATA_DIR` removes everything; the schema is recreated on the next start.
- **Integrity:** before every new analysis, the stored file is checked against its SHA-256 hash. If it went missing or changed on disk, the analysis is refused (HTTP 409), and the dataset page shows **Missing or changed**. Recorded results stay readable.
- **Recorded results are snapshots.** A history entry shows the result exactly as computed when it ran, with the InsightFlow version that produced it. Re-running an analysis creates a new entry; it never edits an old one.
- **Why SQLite:** it is built into Python (no extra package or server), and it enforces what this data needs: a unique content hash, foreign keys with cascading delete, and transactions. DuckDB stays the analytics engine.

**Schema and migrations.** The schema lives in numbered SQL files in `backend/app/storage/migrations/`. The backend applies any migration that hasn't run yet, in order and each in its own transaction, the first time it opens the database, and records it in the `schema_migrations` table. To create or upgrade the database explicitly:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.storage.database
# Database ready: ...\backend\data\insightflow.db (schema version 2)
```

| Migration | What it does |
| --- | --- |
| `0001_create_datasets_and_analyses.sql` | Creates `datasets` and `analyses` (kinds `profile` and `metrics`). |
| `0002_allow_trends_analyses.sql` | Allows the analysis kind `trends`. SQLite can't change a `CHECK` constraint in place, so the `analyses` table is rebuilt: every row is copied with its id, the id counter is carried over (ids of deleted analyses are still never reused), and the index is recreated. Existing profile and metrics history is unchanged and stays readable. |

An existing library is upgraded automatically the next time the backend opens it.

**How metrics are labelled.** When revenue is calculated as quantity × unit price, it is labelled **Gross sales** (before discounts, returns, or refunds). When the file has a `revenue` column, it is labelled **Revenue (as recorded)**, because whether it includes discounts or refunds depends on how the file was made. Amounts have no currency symbol, because the file doesn't say which currency it uses. Values are rounded to 2 decimals for display, and the exact value is shown whenever rounding hides digits.

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

### Sales trends (DuckDB)

`POST /api/uploads/csv/trends` accepts the same upload, follows the same status-code rules, and groups the rows by period. It uses the metrics' rules (same column matching, same per-row revenue, same number rule) plus a date column.

| Form field | Default | Meaning |
| --- | --- | --- |
| `grain` | `month` | `day`, `week` (ISO weeks, Monday to Sunday), or `month`. Anything else returns 422. |
| `order_date_column` | a column named exactly `order_date` | The column that dates each row. |
| `order_id_column`, `quantity_column`, `unit_price_column`, `revenue_column` | exact names, as for the metrics | Same roles as the metrics. Each column can fill only one role (422 otherwise). |

The response has `periods` (each with `start`, inclusive `end`, and `row_count`) and three series, each with one point per period:

| Series | Needs | Per period |
| --- | --- | --- |
| `revenue` | `revenue`, **or** `quantity` + `unit_price` | Sum of the same per-row value `total_revenue` uses. Labelled gross sales or revenue as recorded, exactly like the metric. |
| `order_count` | `order_id` | Distinct order IDs. An order with rows in two periods is counted in each, and flagged in `notes`. |
| `average_order_value` | `order_id` + revenue | Revenue ÷ distinct orders, from rows with both an order ID and a usable revenue value. |

**Dates.** A usable date follows the data-quality check's date rule exactly: a real calendar date written `YYYY-MM-DD` (spaces around it are ignored). `05/01/2026`, `2026-01-05 10:00`, and `2026-02-30` are **not** usable. Rows without a usable date are excluded from every series and reported in `dated_rows`, with line numbers. Nothing is guessed.

**Gaps are not zeros.** Every period between the first and last date is listed. A period with no rows has `row_count: 0` and `value: null` in every series, and a period whose rows have no usable value also has `value: null`. Negative revenue (returns, refunds) is included as-is and flagged.

**Every series reports** `status`, `definition`, `columns_used`, `rows_included`, `rows_excluded`, `notes`, and `points` (`value` and `rows_included` per period). If the file has no usable dates, no date column, or no rows for a series, that series is `unavailable` with the reason in `notes`, and the response is still 200. Dates spanning more than 2,000 periods (for example a mistyped year with daily grouping) are also reported as unavailable, naming the earliest and latest dates and their lines.

```powershell
# Monthly trends for the sample file
curl.exe -F "file=@tests/fixtures/sample_sales.csv" http://127.0.0.1:8000/api/uploads/csv/trends

# Weekly, with your own column names
curl.exe -F "file=@my_sales.csv" -F "grain=week" -F "order_date_column=Day" -F "order_id_column=OrderNo" http://127.0.0.1:8000/api/uploads/csv/trends

# An impossible date (line 6): see it excluded and reported
curl.exe -F "file=@tests/fixtures/messy_sales.csv" -F "grain=day" http://127.0.0.1:8000/api/uploads/csv/trends
```

### Dataset library endpoints

These keep the file (see [Saved datasets: what is stored, and where](#saved-datasets-what-is-stored-and-where)). The in-memory endpoints above never store anything.

| Request | Success | Errors |
| --- | --- | --- |
| `POST /api/datasets` (file in the form field `file`) | **201** `{"created": true, "dataset": {...}}`, or **200** `{"created": false, ...}` with the existing dataset when the same content was already saved | 400, 413, 415, 422 (same rules as the upload endpoints; nothing is stored) |
| `GET /api/datasets` | 200 `{"datasets": [...]}`, newest first | — |
| `GET /api/datasets/{id}` | 200: details, column names, `file_stored` | 404 |
| `DELETE /api/datasets/{id}` | 204: stored file, metadata, and history removed | 404 |
| `GET /api/datasets/{id}/analyses` | 200 `{"analyses": [...]}`, newest first, each with headline numbers (`highlights`) | 404 |
| `POST /api/datasets/{id}/analyses` with JSON `{"kind": "profile"}`, `{"kind": "metrics", "column_mapping": {"quantity": "Qty"}}`, or `{"kind": "trends", "grain": "week", "column_mapping": {"order_date": "Day"}}` | 201: the recorded analysis with its full `result` (trends records also carry their `grain`, which defaults to `month`) | 404; 409 stored file missing or changed; 422 invalid kind, grain, or mapping, `grain` on a non-trends kind, or `order_date` in a metrics mapping (nothing is recorded) |
| `GET /api/datasets/{id}/analyses/{analysis_id}` | 200: one recorded analysis, exactly as stored | 404 (also when the analysis belongs to another dataset) |

```powershell
# Save a file (run it twice: the second answer is 200 with "created": false)
curl.exe -F "file=@tests/fixtures/messy_sales.csv" http://127.0.0.1:8000/api/datasets

# Record a data-quality check, a metrics calculation, and weekly trends for dataset 1
curl.exe -X POST -H "Content-Type: application/json" -d '{\"kind\": \"profile\"}' http://127.0.0.1:8000/api/datasets/1/analyses
curl.exe -X POST -H "Content-Type: application/json" -d '{\"kind\": \"metrics\"}' http://127.0.0.1:8000/api/datasets/1/analyses
curl.exe -X POST -H "Content-Type: application/json" -d '{\"kind\": \"trends\", \"grain\": \"week\"}' http://127.0.0.1:8000/api/datasets/1/analyses

# Read the history, then delete the dataset (file, metadata, and history)
curl.exe http://127.0.0.1:8000/api/datasets/1/analyses
curl.exe -X DELETE http://127.0.0.1:8000/api/datasets/1
```

## Running tests and checks

```powershell
# Backend tests
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest -v
cd ..

# Frontend unit tests, lint, and type check + production build
cd frontend
npm test
npm run lint
npm run build
cd ..
```

The backend tests use a temporary data directory, so they never touch `backend/data/`. They cover the migrations (fresh database, re-runs, rollback of a failed migration, concurrent first use, and upgrading a schema-version-1 library with real profile and metrics history to version 2 without losing or changing it), the sales trends (daily, weekly, and monthly grouping, the date rule checked against the data-quality check's, invalid and mixed dates, gaps, negative revenue, overflow, mappings), the file store (hash-named files, integrity checks, path safety), the dataset rules (duplicates, rejected files, history, deletion, a missing stored file), and every dataset endpoint, plus a check that the in-memory endpoints never write anything.

The frontend tests (Vitest) cover the API clients against a mocked `fetch` (URLs, form fields, JSON bodies, status codes, error messages), page routing, column-mapping rules, file checks, number and date formatting, history descriptions, metric labels, and the sales-trend helpers (period labels without time-zone shifts, the table's empty and unusable periods, chart scale, column geometry, and the screen-reader summary). They run in Node and don't need the backend.

## Known limitations

- **Storage is local and single-user.** Saved files and the database live on the machine running the backend. There are no user accounts, no backups, no sync, and no storage quota or pagination (fine for a personal library, not for a shared server).
- **In-memory analysis uploads the file 4 times** (once per step, and again whenever the trends' grain or date column changes), and its results disappear when the page is reloaded. Saved datasets upload once and keep their results.
- **Recorded results are not recalculated.** A history entry keeps the result its InsightFlow version produced. If the rules change in a later version, re-run the analysis to get a new entry.
- **Datasets can't be renamed or replaced.** To change a saved file, save the new version (a different content hash creates a new dataset) and delete the old one.
- **OneDrive and synced folders.** If the project folder is synced (for example by OneDrive), the database and stored files are synced too. To avoid sync conflicts, set `DATA_DIR` to a folder outside it.
- **No profit, margin, or net revenue.** These need cost data and agreed definitions for returns and refunds.
- **No upload progress bar.** The browser's `fetch` API can't report upload progress, so the page shows the real state of each step (waiting, in progress, done, failed) instead of a percentage.
- **The size warning uses the default limit.** The browser warns above 10 MB (the backend's default `MAX_UPLOAD_MB`). If you change `MAX_UPLOAD_MB`, the server's answer is still the one that counts.
- **CSV format.** Only comma-separated, UTF-8 files with a header row. Dates must be `YYYY-MM-DD` to count as dates.
- **Column mapping can't switch a role off.** A column named exactly like a role (for example `revenue`) is always used for that role.
- **Trends only read `YYYY-MM-DD` dates.** Timestamps (`2026-01-05 10:00`) and other formats are excluded and counted, not converted, so there is no time-zone handling. Weeks are ISO weeks (Monday to Sunday); fiscal calendars are not supported. At most 2,000 periods are returned.
- **Trends follow the metrics' column mapping on the Analyze page.** The grain and the date column are chosen in the Sales trends section; the other roles come from **Map columns** in Retail metrics. In library mode, every change records a new trends analysis.
- **Large files take a few seconds.** For a file near 10 MB, the data-quality and metrics steps each took about 4 seconds on the development laptop.

## Troubleshooting

| What you see | Likely cause | Fix |
| --- | --- | --- |
| UI says **Not connected** / "Could not reach the backend (HTTP 502)" | The FastAPI server isn't running | Start Terminal 1, then click **Check again** |
| `Port 5180 is already in use` | Another frontend is still running | Close the other terminal, or stop it with `Ctrl + C` |
| `[Errno 10048] ... address already in use` (backend) | Something else is using port 8000 | Close the old backend terminal |
| `No module named 'app'` | Command run from the wrong folder | `cd backend` first |
| `uvicorn` / `pytest` not recognized | venv not activated | `.\.venv\Scripts\Activate.ps1` |
| Slow installs or "file in use" errors | OneDrive is syncing `node_modules` / `.venv` | Pause OneDrive sync, or move the project to e.g. `C:\dev\Insightflow` |
| A saved dataset shows **Missing or changed** / HTTP 409 | Its stored file in `DATA_DIR/uploads/` was deleted or edited outside InsightFlow | Delete the dataset in the app and save the file again |
| `database is locked` | Another program (or a sync tool) holds `insightflow.db` | Close it, or set `DATA_DIR` outside synced folders |

## Configuration and secrets

- Backend settings live in `backend/.env` (copied from `backend/.env.example`). `.env` is ignored by Git.
- `DATA_DIR` (default `data`, relative to `backend/`) is where saved datasets live. Absolute paths work too, for example `DATA_DIR=C:/InsightFlowData`.
- `GEMINI_API_KEY` is read **only by the backend**. Never put API keys in `frontend/`. Anything in frontend code is downloaded by every browser that opens the app.

## Project structure

```
Insightflow/
├─ backend/
│  ├─ app/
│  │  ├─ main.py          # Creates the FastAPI app and registers routes
│  │  ├─ config.py        # Settings loaded from .env (secrets stay here)
│  │  ├─ api/health.py    # GET /api/health
│  │  ├─ api/csv_upload.py  # Request checks shared by every CSV upload (field, .csv name, size)
│  │  ├─ api/uploads.py   # POST /api/uploads/csv, /csv/profile, /csv/metrics (in memory, nothing stored)
│  │  ├─ api/datasets.py  # /api/datasets: save, list, details, delete, analyses, history
│  │  ├─ ingestion/csv_parser.py  # CSV content validation (no FastAPI code)
│  │  ├─ ingestion/profiler.py    # Read-only data-quality report
│  │  ├─ analytics/duckdb_loader.py   # Loads validated rows into in-memory DuckDB, as text
│  │  ├─ analytics/retail_metrics.py  # Retail metrics in SQL, only when columns exist
│  │  ├─ datasets/service.py  # Library rules: duplicates, storing, analyzing, history, deleting
│  │  ├─ datasets/models.py   # Response shapes for datasets and analysis records
│  │  ├─ storage/database.py  # SQLite connection + migration runner (python -m app.storage.database)
│  │  ├─ storage/migrations/  # Numbered SQL schema files (0001_*.sql, ...)
│  │  ├─ storage/repository.py  # SQL for datasets and analyses (parameterized)
│  │  └─ storage/file_store.py  # Stored CSV files, named by SHA-256, verified on read
│  ├─ tests/              # one test file per module, plus fixtures/ (sample CSVs)
│  ├─ requirements.txt
│  └─ .env.example
├─ frontend/
│  ├─ src/
│  │  ├─ api/http.ts                  # Shared request sending, timeouts, and clear error messages
│  │  ├─ api/health.ts                # GET /api/health
│  │  ├─ api/uploads.ts               # The three in-memory upload endpoints + response types
│  │  ├─ api/datasets.ts              # The dataset library endpoints + response types
│  │  ├─ lib/                         # Pure logic: routes, column mapping, file checks, formatting, labels
│  │  ├─ hooks/useBackendStatus.ts    # Tracks checking / connected / error state
│  │  ├─ hooks/useCsvAnalysis.ts      # Upload → validate (and save) → profile + metrics workflow
│  │  ├─ hooks/useDatasets.ts         # Library list, dataset details, history, actions
│  │  ├─ hooks/useRoute.ts            # Hash-based page routing (#/datasets/12)
│  │  ├─ pages/                       # Analyze, Saved datasets, Dataset detail
│  │  ├─ components/                  # Upload panel, quality report, metric cards, column mapping, status card
│  │  ├─ App.tsx                      # Header navigation + the current page
│  │  └─ index.css                    # Design tokens and styles
│  └─ vite.config.ts                  # Dev server port + /api proxy to the backend (Vitest uses it too)
├─ docs/INTERVIEW_NOTES.md
└─ README.md
```

## How it fits together

```
Browser ──► Vite dev server (localhost:5180) ──/api/*──► FastAPI (127.0.0.1:8000)
            serves React UI                  proxy       route handlers → ingestion / analytics / datasets
                                                                                                │
                                                          only when saving ──► DATA_DIR/insightflow.db  (SQLite: metadata + history)
                                                                               DATA_DIR/uploads/<sha256>.csv  (stored files)
```

Separation of responsibilities:

- `backend/app/api/` — thin HTTP routes only (validate input, call a module, return the result)
- `backend/app/ingestion/` — reading, validating, and profiling uploaded files
- `backend/app/analytics/` — DuckDB loading and retail metric SQL, testable without HTTP. Column names from uploaded files never appear in SQL: each column gets a generated identifier (`c0`, `c1`, …), and values are passed as query parameters.
- `backend/app/datasets/` — the dataset library's rules (what counts as a duplicate, when a file is stored, how analyses are recorded). It reuses the same parser, profiler, and metrics code as the in-memory endpoints.
- `backend/app/storage/` — persistence only: SQLite (schema, migrations, parameterized SQL) and the stored files.
- `frontend/src/` — displays what the API returns and never recalculates metrics. It only adds up the per-column counts for the summary tiles. The backend stays authoritative for every validation rule.
- `backend/app/ai/` — *(planned, not built yet)* an AI provider interface, so Gemini can be swapped or mocked in tests

## Roadmap

1. ✅ Project foundation
2. ✅ CSV import and data-quality validation (upload UI, structure check, quality report, saved datasets with analysis history)
3. 🔄 Retail KPIs (quantity, gross sales/revenue, orders, AOV done, with dashboard) and profitability analysis (not started)
4. Evidence-backed change investigations
5. Natural-language questions answered with verifiable SQL
