# InsightFlow AI

An evidence-first retail analytics platform. Analysts will import retail data, validate its quality, analyze profitability, investigate business changes, and ask natural-language questions answered with verifiable SQL results.

> **Current status: Phase 2 in progress — CSV ingestion and first analytics.** In the browser you can upload a CSV, see why it was rejected (if it was), review a read-only data-quality report, see the basic retail metrics its columns support, follow **sales trends** (revenue, orders, and average order value by day, week, or month), rank **products and categories** by revenue, quantity, and orders, and read **key findings**: plain-English statements of what changed, each backed by the figures, periods, and rows behind it. Everything is calculated with DuckDB; no AI is needed. You choose per upload whether the file is **saved to the dataset library** (stored on the server's disk with its analysis history, until you delete it) or **analyzed in memory only** (nothing stored). Profit is intentionally not calculated yet (see [Known limitations](#known-limitations)).

## Tech stack

| Layer     | Tools                                          |
| --------- | ---------------------------------------------- |
| Frontend  | React 19, TypeScript, Vite                     |
| Backend   | Python, FastAPI, Pydantic Settings             |
| Analytics | DuckDB (in-memory SQL)                         |
| Storage   | SQLite (built into Python) for dataset metadata and analysis history; saved CSV files on local disk |
| AI        | Optional, off by default: a free local model through [Ollama](https://ollama.com) rewrites the key findings as a short summary. A provider interface leaves room for Gemini later. |
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
4. **Read the key findings.** The first results section lists what the numbers show, most important first: the latest complete period against the one before (revenue, orders, average order value), streaks, unusual periods, the highest and lowest periods, the products and categories that moved most, how concentrated revenue is, and negative revenue. Each finding opens to its **Evidence** (values, compared periods, rows). **About this file** lists caveats such as partly covered periods, and **Not assessed** says which checks could not run and why. Findings follow the period and date column chosen in Sales trends and the columns chosen in Product & category performance. They describe; they never claim a cause.
5. **Review data quality.** Summary tiles (rows, columns, duplicate rows, missing values, type mismatches), the duplicate rows with their line numbers, and a table with each column's inferred type, missing values, mismatched values (with line numbers), and status. The exact definition of every check is under **How these checks are defined**.
6. **Review retail metrics.** Each metric card shows its value, the API's definition, the columns used, how many rows were included and excluded, and any notes. Metrics the file can't support are marked **Unavailable**, with the reason from the API.
7. **Map columns (optional).** If your columns are named differently (for example `Qty` instead of `quantity`), open **Map columns**, pick a column for each role, and click **Apply mapping**. Each column can fill only one role. The mapping applies to the metrics, the sales trends, the product and category rankings, and the key findings. For a saved file, every mapping you apply is recorded as a new analysis.
8. **Review sales trends.** A column chart of **Gross sales** (or **Revenue (as recorded)**), **Orders**, or **Average order value** per period, with every period in a table below it. Choose **Group by** Day, Week (Monday to Sunday), or Month (the default), and the **Date column** if yours is not named `order_date`. Hover a period, or focus the chart and use the arrow keys, to read its value. Periods with no rows are left empty, never drawn as zero, and rows without a usable date are counted with their line numbers. With many periods (for example two years of days), the chart switches from columns to a line.
9. **Rank products and categories.** A bar chart of the top 10 products (or categories, with the **Products / Categories** switch) by **Gross sales**, **Total quantity**, **Orders**, or **Rows**, each value printed at its bar, and every listed group in a table with its share of revenue, its rows, and the categories a product is filed under (or how many products a category holds). Choose the **Product column** and **Category column** if yours are not named `product` and `category`. A file without one of them shows that breakdown as unavailable, with the reason. Labels that differ only by case or spacing, and products filed under more than one category, are flagged, never merged.
10. **Analyze another file** or **Clear results** to start over. The results on this page stay until then (also while you browse saved datasets), but disappear when the page is reloaded. Saved datasets are not affected by clearing.
11. **Browse saved datasets.** Open **Saved datasets** in the header to see every saved file. Open one to see its details (rows, columns, stored-file status, SHA-256), its **analysis history** (newest first), and any recorded result exactly as it was stored. From there you can run a new data-quality check, calculate metrics or trends, rank products, find insights (with a different column mapping, grain, date, product, or category column if needed), ask for an optional AI summary of saved key findings (see below), or **delete the dataset**, which asks for confirmation first.

**Duplicate uploads.** Saving a file whose content is already in the library (even under another name) does not store a second copy. The page says **Already in the dataset library**, names the existing dataset, and adds the new results to its history.

Sample files to try are in `backend/tests/fixtures/`: `sample_sales.csv` (clean), `messy_sales.csv` (missing values, a duplicate row, `N/A`, an impossible date), `numeric_edge_cases.csv`, `order_lines.csv`, `no_sales_columns.csv`, and `catalog_sales.csv` (products and categories, with a case variant, a padded label, a product in two categories, blank labels, and a refund).

**Endpoints the UI calls** (through the Vite proxy, so the browser only talks to `localhost:5180`):

| Step | Analyze in memory only | Save to the dataset library |
| --- | --- | --- |
| Backend status card | `GET /api/health` | `GET /api/health` |
| Validate | `POST /api/uploads/csv` (file in the form field `file`) | `POST /api/datasets` (stores the file) |
| Data quality | `POST /api/uploads/csv/profile` (uploads the file again) | `POST /api/datasets/{id}/analyses` with `{"kind": "profile"}` |
| Retail metrics | `POST /api/uploads/csv/metrics`, plus `order_id_column`, `quantity_column`, `unit_price_column`, `revenue_column` only for roles you mapped | `POST /api/datasets/{id}/analyses` with `{"kind": "metrics", "column_mapping": {...}}` |
| Sales trends | `POST /api/uploads/csv/trends`, plus `grain`, and `order_date_column` and the other `*_column` fields only for roles you chose | `POST /api/datasets/{id}/analyses` with `{"kind": "trends", "grain": "week", "column_mapping": {...}}` |
| Products & categories | `POST /api/uploads/csv/performance`, plus `product_column`, `category_column`, and the other `*_column` fields only for roles you chose | `POST /api/datasets/{id}/analyses` with `{"kind": "performance", "column_mapping": {...}}` |
| Key findings | `POST /api/uploads/csv/insights`, plus `grain` and the `*_column` fields only for roles you chose | `POST /api/datasets/{id}/analyses` with `{"kind": "insights", "grain": "month", "column_mapping": {...}}` |
| Saved datasets pages | — | `GET /api/datasets`, `GET /api/datasets/{id}`, `GET /api/datasets/{id}/analyses`, `GET /api/datasets/{id}/analyses/{analysis_id}`, `DELETE /api/datasets/{id}` |

Key findings, data quality, retail metrics, sales trends, and product & category performance run in parallel after validation succeeds, and each can fail and be retried on its own. Changing the grain or the date column re-runs the trends and the findings; changing the product or category column re-runs the rankings and the findings.

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
| `0003_allow_performance_analyses.sql` | Allows the analysis kind `performance`, with the same rebuild steps as 0002. Tested on a version-2 library holding profile, metrics, and trends history: every record stays readable and unchanged, and the id counter carries over. |
| `0004_allow_insights_analyses.sql` | Allows the analysis kind `insights`, with the same rebuild steps. Tested on a version-3 library holding profile, metrics, trends, and performance history. |
| `0005_create_narrations.sql` | Adds the `narrations` table for optional AI summaries (one row per attempt). It references `datasets`, not `analyses`: adding an analysis kind rebuilds `analyses`, which would otherwise delete every summary through the cascade. Summaries are deleted with their dataset. |

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

### Product & category performance (DuckDB)

`POST /api/uploads/csv/performance` accepts the same upload, follows the same status-code rules, and breaks the rows down by product and by category. It uses the metrics' rules (same column matching, same per-row revenue, same number rule) plus two label columns.

| Form field | Default | Meaning |
| --- | --- | --- |
| `product_column` | a column named exactly `product` | The column that names each row's product. |
| `category_column` | a column named exactly `category` | The column that names each row's category. |
| `order_id_column`, `quantity_column`, `unit_price_column`, `revenue_column` | exact names, as for the metrics | Same roles as the metrics. Each column can fill only one role (422 otherwise). |

The response has a `products` and a `categories` breakdown. Each lists its groups, highest first, with:

| Field | Per group |
| --- | --- |
| `revenue` | Sum of the same per-row value `total_revenue` uses (gross sales, or revenue as recorded). |
| `revenue_share` | That revenue as a percentage of the breakdown's total, rounded to 2 decimals. Empty when the total is zero or negative. |
| `quantity` | Sum of the quantity column. |
| `order_count` | Distinct order IDs among the group's rows. An order with several products counts under each, and this is flagged. |
| `row_count` | Rows with this label. |
| `categories` (products) | The categories the product's rows are filed under. |
| `product_count` (categories) | Distinct products among the category's rows. |
| `similar_labels` | Other labels that differ from this one only by letter case or spacing. |

**Labels.** A label is the cell's exact text after trimming surrounding spaces, so `" Oat Milk "` and `"Oat Milk"` are one product. Blank labels are excluded and counted with line numbers. `Green Tea`, `green tea`, and `Green  Tea` stay **separate** groups and are flagged in `notes`, never merged. Products filed under more than one category are flagged too. Nothing is guessed: `Product` or `SKU` are only used when you choose them.

**Ranking.** By revenue; by quantity when revenue is unavailable; by row count when both are. Groups without a usable value come last, and ties are broken by label in code point order, so the same file always gives the same ranking (`ranked_by` says which measure was used).

**At most 1,000 groups are listed.** When there are more, `remaining` sums the rest (group count, rows, revenue, quantity, and distinct orders), so the listed groups plus `remaining` always add up to the totals. In the browser, a capped breakdown can only be ranked the way the API ranked it, because re-ranking the listed groups could miss the real top ones.

**Missing columns.** Without a `product` (or `category`) column, that breakdown is `unavailable` with the reason in `notes`; the other still works. A measure whose column is missing (for example no `order_id`) is unavailable on its own. Profit is not calculated (see [Known limitations](#known-limitations)).

```powershell
# Products and categories for the catalog fixture
curl.exe -F "file=@tests/fixtures/catalog_sales.csv" http://127.0.0.1:8000/api/uploads/csv/performance

# Your own column names
curl.exe -F "file=@my_sales.csv" -F "product_column=SKU" -F "category_column=Department" http://127.0.0.1:8000/api/uploads/csv/performance
```

### Key findings (deterministic insights)

`POST /api/uploads/csv/insights` accepts the same upload and the same column fields as the endpoints above, plus `grain` (`day`, `week`, or `month`, default `month`). It runs the trends and the product and category performance on the same rows and turns them into findings. **No AI is involved**: every sentence comes from a fixed template filled with computed figures.

| Finding | What it says | Only when |
| --- | --- | --- |
| Period comparison | Revenue, orders, and average order value in the latest complete period against the one before, with the change and percentage. | The last two complete periods each have at least 5 rows. |
| Streak | The metric rose (or fell) in each of the last N comparisons. | At least 3 consecutive complete periods with 5+ rows. |
| Unusual period | A period far from the typical one (median), with both values. | At least 8 complete periods with 5+ rows; robust score above 3.5. |
| Highest and lowest | The highest and lowest complete periods. | At least 3 complete periods with 5+ rows. |
| Movers | The product (and category) with the largest increase and decrease between the last two complete periods. | The comparison above is possible; a product needs 5+ rows in those two periods. |
| Concentration | The top product's (and category's) share of revenue, and how many make up 80%. | Total revenue is positive and there are at least 2 labels. |
| Negative revenue | How many rows have negative revenue, their total, and its share of positive revenue. | Some rows are negative. |

**Safeguards.** These are returned with every result in `thresholds`:
- **Complete periods only.** A period is complete when the file's usable dates cover it from its first to its last day. A partly covered first or last period (for example data starting on Jan 5) is never compared with a full one. It is listed under `coverage.partial_periods` and in the caveats. Complete coverage does not prove that every sale was recorded, and the definition says so.
- **No percentage from a zero or negative starting value.** The absolute change is still given.
- **Not assessed, never silent.** A check that can't run (no date column, too few periods, too few rows, no category column) is listed in `not_assessed` with the reason.
- **Facts, not causes.** Findings say what the numbers show. Suggestions are phrased as things to check ("Check how this file records returns") and kept apart from the findings. A test fails if any text says "because", "due to", "driven by", or similar.
- **Importance** comes from the size of the change (20% or more is high, 5% or more is medium), never from the wording. Findings are ordered by importance, then by a fixed order, so the same file always gives the same list.

```powershell
# Findings by month for a file with order dates
curl.exe -F "file=@my_sales.csv" http://127.0.0.1:8000/api/uploads/csv/insights

# By week, with your own date column
curl.exe -F "file=@my_sales.csv" -F "grain=week" -F "order_date_column=Day" http://127.0.0.1:8000/api/uploads/csv/insights
```

### Optional AI summary (local Ollama)

Off by default; everything above works without it. When turned on, the page of a **saved** key-findings analysis shows **Write a summary**: a model running on your own computer rewrites the findings as 2 to 4 sentences.

**Turn it on (free):**
1. Install [Ollama](https://ollama.com) and pull a small model: `ollama pull llama3.2:3b` (about 2 GB).
2. In `backend/.env`: `INSIGHTS_NARRATOR=ollama` (and `OLLAMA_MODEL` if you pulled a different model).
3. Restart the backend. `GET /api/insights/narrator` says whether it is ready, and if not, what to do.

**What it sees.** Only the findings' own sentences, titles, importance, coverage dates, and file caveats. Never CSV rows, order IDs, column names, line numbers, or not-assessed reasons. `OLLAMA_URL` must point to this computer (localhost); any other address is refused at startup, so nothing leaves the machine. Findings are passed as a quoted data block, and the instructions tell the model to treat them as data, not instructions.

**Its text is untrusted.** It is shown only if it passes every check:
- every number and every quoted product or category name appears in the findings;
- no claim of a cause ("because", "due to", "driven by", ...) and no prediction ("will", "likely to", "forecast", ...);
- plain text only (no links, markdown, or HTML) and at most 900 characters.

Otherwise the page shows the **template summary** (the top findings' own sentences) and says why. Every attempt is recorded in the `narrations` table with the provider, model, prompt version (`narration-v1`), status (`accepted`, `rejected`, or `failed`), and the reasons. A rejected reply is kept for audit and never shown.

| Request | Result |
| --- | --- |
| `GET /api/insights/narrator` | 200 `{"enabled", "provider", "model", "available", "reason"}`. No URLs or keys. |
| `GET /api/datasets/{id}/analyses/{analysis_id}/narrations` | 200 `{"narrations": [...]}`, newest first. 404 for an unknown dataset or analysis. |
| `POST /api/datasets/{id}/analyses/{analysis_id}/narrations` | 201: the recorded attempt, with `text` to show and `source` (`ai` or `template`). 409 when no narrator is configured or reachable, or one is already running for this analysis; 422 when the analysis is not key findings; 404 as above. |

**Cost and speed.** $0: no account, no key, no cloud. On a laptop CPU (for example a Ryzen 7 5700U with integrated graphics) a 3B model takes roughly 20 to 60 seconds per summary; `OLLAMA_TIMEOUT_SECONDS` (default 120) limits the wait. Small models often paraphrase loosely; when they do, the checks reject the text and the template is shown, by design.

### Dataset library endpoints

These keep the file (see [Saved datasets: what is stored, and where](#saved-datasets-what-is-stored-and-where)). The in-memory endpoints above never store anything.

| Request | Success | Errors |
| --- | --- | --- |
| `POST /api/datasets` (file in the form field `file`) | **201** `{"created": true, "dataset": {...}}`, or **200** `{"created": false, ...}` with the existing dataset when the same content was already saved | 400, 413, 415, 422 (same rules as the upload endpoints; nothing is stored) |
| `GET /api/datasets` | 200 `{"datasets": [...]}`, newest first | — |
| `GET /api/datasets/{id}` | 200: details, column names, `file_stored` | 404 |
| `DELETE /api/datasets/{id}` | 204: stored file, metadata, and history removed | 404 |
| `GET /api/datasets/{id}/analyses` | 200 `{"analyses": [...]}`, newest first, each with headline numbers (`highlights`) | 404 |
| `POST /api/datasets/{id}/analyses` with JSON `{"kind": "profile"}`, `{"kind": "metrics", "column_mapping": {"quantity": "Qty"}}`, `{"kind": "trends", "grain": "week", "column_mapping": {"order_date": "Day"}}`, `{"kind": "performance", "column_mapping": {"product": "SKU"}}`, or `{"kind": "insights", "grain": "week"}` | 201: the recorded analysis with its full `result` (trends and insights records also carry their `grain`, which defaults to `month`) | 404; 409 stored file missing or changed; 422 invalid kind, grain, or mapping, `grain` outside trends and insights, `order_date` outside trends and insights, or `product`/`category` outside performance and insights (nothing is recorded) |
| `GET /api/datasets/{id}/analyses/{analysis_id}` | 200: one recorded analysis, exactly as stored | 404 (also when the analysis belongs to another dataset) |

```powershell
# Save a file (run it twice: the second answer is 200 with "created": false)
curl.exe -F "file=@tests/fixtures/messy_sales.csv" http://127.0.0.1:8000/api/datasets

# Record a data-quality check, a metrics calculation, weekly trends, product rankings, and key findings for dataset 1
curl.exe -X POST -H "Content-Type: application/json" -d '{\"kind\": \"profile\"}' http://127.0.0.1:8000/api/datasets/1/analyses
curl.exe -X POST -H "Content-Type: application/json" -d '{\"kind\": \"metrics\"}' http://127.0.0.1:8000/api/datasets/1/analyses
curl.exe -X POST -H "Content-Type: application/json" -d '{\"kind\": \"trends\", \"grain\": \"week\"}' http://127.0.0.1:8000/api/datasets/1/analyses
curl.exe -X POST -H "Content-Type: application/json" -d '{\"kind\": \"performance\"}' http://127.0.0.1:8000/api/datasets/1/analyses
curl.exe -X POST -H "Content-Type: application/json" -d '{\"kind\": \"insights\"}' http://127.0.0.1:8000/api/datasets/1/analyses

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

The backend tests use a temporary data directory, so they never touch `backend/data/`. They cover the migrations (fresh database, re-runs, rollback of a failed migration, concurrent first use, and upgrading real version-1, -2, and -3 libraries, with their earlier history, without losing or changing anything), the key findings (each finding's exact wording, complete-period rules, partial first and last periods, too few periods or rows, zero and negative baselines, streaks, unusual periods, movers, concentration, negative revenue, missing columns, fixed ordering, and a check that no text claims a cause), the optional narrator (what it is sent, with no rows, order IDs, or line numbers; the output checks for numbers, names, causes, predictions, and markup; accepted, rejected, and failed attempts; the template fallback; one narration at a time; localhost-only settings; and the Ollama adapter against a stand-in server on localhost, with no model or internet needed), the product and category rankings (trimming, blank labels, case and spacing variants, products in several categories, ranking and ties, shares, missing columns, the 1,000-group cap and its summary, overflow, mappings), the sales trends (daily, weekly, and monthly grouping, the date rule checked against the data-quality check's, invalid and mixed dates, gaps, negative revenue, overflow, mappings), the file store (hash-named files, integrity checks, path safety), the dataset rules (duplicates, rejected files, history, deletion, a missing stored file), and every dataset endpoint, plus a check that the in-memory endpoints never write anything.

The frontend tests (Vitest) cover the API clients against a mocked `fetch` (URLs, form fields, JSON bodies, status codes, error messages), page routing, column-mapping rules, file checks, number and date formatting, history descriptions, metric labels, and the sales-trend helpers (period labels without time-zone shifts, the table's empty and unusable periods, chart scale, column geometry, and the screen-reader summary), and the product and category helpers (ranking with the backend's tie-break, the ranking choices for capped breakdowns, labels, shares, and the bar chart's scale), and the key-findings helpers (summaries, coverage text, date ranges, grouping by importance, the safeguards in plain words, and evidence formatting), and the AI-summary labels (when the panel is hidden, unavailable, or ready, and how accepted, rejected, and failed summaries are described). They run in Node and don't need the backend.

## Known limitations

- **Storage is local and single-user.** Saved files and the database live on the machine running the backend. There are no user accounts, no backups, no sync, and no storage quota or pagination (fine for a personal library, not for a shared server).
- **In-memory analysis uploads the file 6 times** (once per step, and again whenever the trends' grain or date column, or the product or category column, changes), and its results disappear when the page is reloaded. Saved datasets upload once and keep their results.
- **Recorded results are not recalculated.** A history entry keeps the result its InsightFlow version produced. If the rules change in a later version, re-run the analysis to get a new entry.
- **Datasets can't be renamed or replaced.** To change a saved file, save the new version (a different content hash creates a new dataset) and delete the old one.
- **OneDrive and synced folders.** If the project folder is synced (for example by OneDrive), the database and stored files are synced too. To avoid sync conflicts, set `DATA_DIR` to a folder outside it.
- **No profit, margin, or net revenue.** These need cost data and agreed definitions for returns and refunds.
- **No upload progress bar.** The browser's `fetch` API can't report upload progress, so the page shows the real state of each step (waiting, in progress, done, failed) instead of a percentage.
- **The size warning uses the default limit.** The browser warns above 10 MB (the backend's default `MAX_UPLOAD_MB`). If you change `MAX_UPLOAD_MB`, the server's answer is still the one that counts.
- **CSV format.** Only comma-separated, UTF-8 files with a header row. Dates must be `YYYY-MM-DD` to count as dates.
- **Column mapping can't switch a role off.** A column named exactly like a role (for example `revenue`) is always used for that role.
- **Trends only read `YYYY-MM-DD` dates.** Timestamps (`2026-01-05 10:00`) and other formats are excluded and counted, not converted, so there is no time-zone handling. Weeks are ISO weeks (Monday to Sunday); fiscal calendars are not supported. At most 2,000 periods are returned.
- **Key findings are deliberately simple.** They compare the last two complete periods only, look for unusual periods with a single robust rule, and don't model seasonality or forecast. The safeguards are fixed values (see `thresholds`), and the wording is English templates. Findings describe what changed; explaining why is left to you.
- **The AI summary is optional and checked, not verified.** The checks catch invented numbers, unknown quoted names, causal and predictive wording, and markup. They can't judge emphasis or tone, and unquoted names are not checked. It only runs on saved key findings, needs Ollama on the same computer, and is slow on a CPU. Gemini is not implemented.
- **Product and category labels are compared as exact text.** Variants are flagged but never merged, so `Green Tea` and `green tea` are ranked separately until the file is fixed. There is no product hierarchy (subcategories) and no per-product average price or margin. At most 1,000 groups are listed per breakdown.
- **Trends and rankings follow the metrics' column mapping on the Analyze page.** The grain and the date column are chosen in the Sales trends section; the other roles come from **Map columns** in Retail metrics. The product and category columns are chosen in their own section. In library mode, every change records a new analysis, and each upload records five.
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
- `INSIGHTS_NARRATOR` (default `none`), `OLLAMA_URL` (must be localhost), `OLLAMA_MODEL`, and `OLLAMA_TIMEOUT_SECONDS` control the optional AI summary. Nothing is needed when it is off.
- `GEMINI_API_KEY` is reserved and not used yet. Like any key, it is read **only by the backend**. Never put API keys in `frontend/`. Anything in frontend code is downloaded by every browser that opens the app.

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
│  │  ├─ analytics/sales_trends.py    # Revenue, orders, and AOV by day, week, or month
│  │  ├─ analytics/product_performance.py  # Product and category rankings (1,000-group cap)
│  │  ├─ analytics/insights.py        # Deterministic key findings with safeguards
│  │  ├─ analytics/evidence.py        # Shared "(lines 4, 7, ...)" evidence for notes
│  │  ├─ narration/       # Optional local AI summary: facts, prompt, output checks, Ollama, records
│  │  ├─ api/narration.py # Narrator status and summaries of saved key findings
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
│  │  ├─ api/narration.ts             # The optional AI-summary endpoints
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
- `backend/app/narration/` — the optional AI summary. A `Narrator` protocol (Ollama today; Gemini could implement it later), the facts it may see, the prompt, the output checks, and the record of every attempt. Tests use a fake narrator, so no model is needed.

## Roadmap

1. ✅ Project foundation
2. ✅ CSV import and data-quality validation (upload UI, structure check, quality report, saved datasets with analysis history)
3. 🔄 Retail KPIs (quantity, gross sales/revenue, orders, AOV done, with dashboard) and profitability analysis (not started)
4. ✅ Evidence-backed key findings (deterministic), with an optional local AI summary
5. Natural-language questions answered with verifiable SQL
