# InsightFlow production readiness audit

**Status:** Phases A to D complete. The approved fixes are implemented with regression tests and verified (section 5); the remaining findings are open and listed with their remediation. **Not committed.**
**Audited commit:** `fb82dcd` on `master` (in sync with `insightflow/master`, clean working tree).
**Scope:** backend (FastAPI, DuckDB, SQLite, file store, narration), frontend (React/Vite), configuration, dependencies, and deployment assumptions.
**Method:** code reading plus local experiments in a scratch directory (never the project's `backend/data`). Each finding says whether it is **confirmed** (reproduced or read directly in the code that runs) or **needs verification**.

Severity scale: **Critical** (exploitable data loss or exposure in a realistic deployment), **High** (one request can disrupt service, or a stated safeguard does not hold), **Medium** (resource or operational risk under load or misconfiguration), **Low** (hygiene, efficiency), **Info** (documented limitation).

---

## 1. Summary

InsightFlow is a **single-user, local-first** app. On the default setup (backend on `127.0.0.1:8000`, Vite dev proxy on `localhost:5180`) most findings need local access to exploit. **It is still not ready for deployment on a network**: there is no authentication (F5) and no production serving setup (F6). See the checklist in section 7.

| # | Finding | Severity | Status after Phase C |
| --- | --- | --- | --- |
| F1 | Ollama "localhost only" safeguard is bypassed by proxy environment variables | High | **Fixed** (verified) |
| F2 | Duplicate-header check is quadratic: one wide header pins a CPU for hours | High | **Fixed** (verified) |
| F3 | Six in-memory endpoints parse CSV on the event loop, stalling every request | High | **Partly fixed**: parsing moved off the event loop; CPU-bound Python work still competes for the GIL |
| F4 | Upload size limit applies only after the whole body is written to disk | High (network) | **Fixed in the app** (verified on a real server); a reverse-proxy limit is still recommended |
| F5 | No authentication or authorization; all datasets are readable and deletable by any client | Critical (network) / Info (local) | Open (architectural) |
| F6 | No production serving story: relative `/api` URL, Vite dev proxy only, no CORS | Medium | Open |
| F7 | Repeated uploads, parsing, and computation; high memory per parse | Medium | Open (architectural) |
| F8 | No DuckDB resource limits, server-side timeouts, or rate limiting | Medium | **Partly fixed**: DuckDB thread and memory limits; timeouts and rate limits open |
| F9 | API docs (`/docs`, `/openapi.json`) always on; `APP_ENV=production` changes nothing | Low | **Fixed** |
| F10 | History grows without bound; listing parses every stored result | Low | Open |
| F11 | Migrations re-run on every database open | Low | Open |
| F12 | Health endpoint is liveness only; no readiness check | Low | **Fixed** (`/api/health/ready`) |
| F13 | Python dependencies unpinned, test tools in runtime requirements, no Python vulnerability scan | Low | Open |
| F14 | Narration "one at a time" guard is per process | Low | Open (documented) |
| F15 | Data at rest is unencrypted with no retention policy | Info | Open (documented) |
| F16 | No column-count limit (wide files are costly beyond the header check) | Medium | **Fixed** (at most 1,000 columns) |
| F17 | DuckDB spills data to `.tmp` in the server's working directory when over its memory limit | Medium | **Fixed** (found in Phase C) |
| F18 | DuckDB prints a progress bar to the server's output on long queries | Low | **Fixed** (found in Phase C) |

## 2. Request lifecycle and data flow

This section describes the code after the Phase C fixes; where the behaviour changed, the original (Phase A) behaviour is noted.

### In-memory analysis (`POST /api/uploads/csv`, `/profile`, `/metrics`, `/trends`, `/performance`, `/insights`)

0. `RequestBodyLimit` (`backend/app/api/request_limits.py`) refuses a declared `Content-Length` over `MAX_UPLOAD_MB` + 256 KB with 413 before any body is read, and cuts off a body without a length with 413 once it passes that size (F4). *Phase A: no limit until step 2.*
1. Starlette parses the multipart body. Each file part is written to a `SpooledTemporaryFile` (first 1 MB in memory, the rest on disk) **before** the handler runs (`starlette/formparsers.py`, `on_headers_finished`, `spool_max_size = 1MB`; no file size cap of its own, so step 0 bounds it).
2. `read_csv_upload` (`backend/app/api/csv_upload.py`) checks the field, the `.csv` name, and reads at most `MAX_UPLOAD_MB` + 1 bytes from the spooled file (413 if larger).
3. `parse_or_422` → `parse_csv` (`backend/app/ingestion/csv_parser.py`) checks the header (at most 1,000 columns, duplicates found in one pass), decodes UTF-8, and builds a Python list of every row. It runs in the thread pool (`await run_in_threadpool(parse_or_422, content)`, `backend/app/api/uploads.py`). *Phase A: it ran directly on the event loop (F3), and the header check was quadratic (F2).*
4. Column roles are resolved; invalid mappings return 422.
5. The analysis runs in the thread pool (`run_in_threadpool`): `load_into_duckdb` creates one `TemporaryDirectory` per analysis, opens an in-memory DuckDB connection with `DUCKDB_THREADS`, `DUCKDB_MEMORY_LIMIT`, and its spill directory inside that temporary directory, writes the rows to a temporary CSV there, bulk-loads it, deletes the CSV, runs queries, closes the connection in `finally`, and then removes the directory (`backend/app/analytics/duckdb_loader.py`). An out-of-memory error returns 413. *Phase A: DuckDB defaults (all cores, about 80% of RAM, spills to `.tmp` in the working directory).*
6. The result is returned. Nothing is stored. FastAPI closes the uploaded file after the response.

The frontend's in-memory workflow sends the same file **six times** (validate, then profile, metrics, trends, performance, insights in parallel), so each step repeats steps 1 to 5 (`frontend/src/hooks/useCsvAnalysis.ts`).

### Saved datasets (`/api/datasets...`)

1. `POST /api/datasets`: same steps 1 and 2, then in the thread pool `DatasetService.save_dataset` hashes the bytes (SHA-256), returns the existing dataset if the hash exists, otherwise parses (rejecting invalid files before anything is stored), writes `DATA_DIR/uploads/<sha256>.csv` atomically (temp name + `os.replace`), and inserts the metadata row (`backend/app/datasets/service.py`, `backend/app/storage/file_store.py`).
2. `POST /api/datasets/{id}/analyses`: reads the stored file, re-checks its hash (409 if missing or changed), parses it, runs the analysis, and inserts the result into `analyses` in one transaction. A failure before the insert leaves history untouched.
3. Saved mode in the UI runs five analyses after saving, each re-reading, re-hashing, and re-parsing the stored file.
4. `DELETE /api/datasets/{id}`: deletes the stored file, then the rows (`ON DELETE CASCADE` removes analyses and narrations).
5. Narration (`POST /api/datasets/{id}/analyses/{analysis_id}/narrations`, off by default): loads the stored insights result, builds facts (findings text only), calls Ollama, validates the reply, and records the attempt in `narrations` (`backend/app/narration/`).

### Where data lives

| Data | Location | Removed when |
| --- | --- | --- |
| Request bodies (all endpoints), at most about `MAX_UPLOAD_MB` + 256 KB each | Starlette spooled temp files (OS temp dir) | After the response, or as soon as a request cut off with 413 is released |
| DuckDB working copy, temporary CSV, and spilled data | One `TemporaryDirectory` + in-memory DuckDB per analysis | End of the analysis (`finally`, then the directory is removed) |
| Saved CSV files | `DATA_DIR/uploads/<sha256>.csv` | Dataset deleted |
| Metadata, analysis results, narrations (incl. rejected model text) | `DATA_DIR/insightflow.db` (SQLite) | Dataset deleted (cascade) |
| Frontend results | Browser memory | Page reload or "Clear results" |

Isolation: none between clients (there are no users). Dataset IDs are sequential integers. There is no shared in-memory analysis state between requests except the narration in-flight set.

---

## 3. Confirmed findings

These are the Phase A findings as recorded. Section 5 describes the fixes and their verification.

### F1. Ollama "localhost only" safeguard is bypassed by proxy settings (High, confirmed)

- **Evidence:** `backend/app/config.py` `_ollama_on_this_computer` validates `OLLAMA_URL` is a loopback address. `backend/app/narration/ollama.py` `_request` then calls `urllib.request.urlopen`, which uses the default opener: it **honours `HTTP_PROXY`/`HTTPS_PROXY`** and has no automatic localhost bypass unless `NO_PROXY` lists it. Experiment (scratch script, fake proxy on 127.0.0.1, narrator pointed at `http://127.0.0.1:11555` where nothing listens): with `HTTP_PROXY` set, both `GET http://127.0.0.1:11555/api/tags` and `POST http://127.0.0.1:11555/api/generate` (158-byte body containing the prompt) **arrived at the proxy**, and the narrator reported success.
- **Also:** the default opener follows redirects for GET (the status check), so a local service could redirect the status request off the machine. POST redirects (301/302/303) are re-sent as GET **without** the body, and 307/308 POST redirects raise an error, so findings are not forwarded by redirects.
- **Impact:** on a machine with a proxy configured (common on corporate networks), findings text (figures and product names) would be sent to the proxy, which may be remote, despite the documented guarantee. Only when the narrator is enabled (off by default).
- **Remediation:** use a dedicated opener with `ProxyHandler({})` (no proxies) and a redirect handler that refuses all redirects. Regression tests: a fake proxy in `HTTP_PROXY` receives nothing; a redirect raises `NarratorError`.

### F2. Duplicate-header check is quadratic (High, confirmed)

- **Evidence:** `backend/app/ingestion/csv_parser.py` `_read_header`: `sorted({name for name in columns if columns.count(name) > 1})` is O(n²) in the column count. Measured: 2,000 columns 0.08 s, 4,000 columns 0.40 s, 8,000 columns 1.46 s (about 4x per doubling). A 10 MB header can hold over a million short column names; extrapolated, that is many hours of CPU for one request.
- **Impact:** a single upload pins a CPU. On the in-memory endpoints it also freezes the whole server (see F3). Saved-dataset uploads tie up a worker thread.
- **Remediation:** count names once with `collections.Counter` (same error message, same sorted output). Regression test: a 50,000-column header is checked in well under a second, and duplicates are still reported exactly as before.

### F3. CSV parsing blocks the event loop on six endpoints (High, confirmed)

- **Evidence:** `backend/app/api/uploads.py` calls `parse_or_422(content)` synchronously inside `async def` handlers (lines 75, 89, 107, 136, 166, 199); only the analysis afterwards uses `run_in_threadpool`. Parsing a 10 MB small-cell file takes about 3.1 s (measured without tracing). Experiment (scratch server on port 8011): `GET /api/health` took **0.06 s** normally and **2.0 s** while one 9 MB validate upload was parsing.
- **Impact:** every request, including the health check and other users' requests, waits while any in-memory upload is parsed. The UI sends six such uploads per file, so the stalls add up. Saved-dataset endpoints are not affected (they parse in the thread pool).
- **Remediation:** `parsed = await run_in_threadpool(parse_or_422, content)` in the six handlers. No behaviour change. Regression test: parsing does not run on the event loop thread.

### F4. Upload size limit applies only after the body is spooled to disk (High for network deployment, confirmed)

- **Evidence:** Starlette 1.7.0 `MultiPartParser` stores each file part in `SpooledTemporaryFile(max_size=1MB)` with no total size limit; `max_files=1000` file parts per request are accepted. `read_csv_upload` checks `MAX_UPLOAD_MB` only after parsing finished. Uvicorn sets no body size limit.
- **Impact:** a client can stream arbitrarily large bodies (or up to 1,000 large file parts), filling the server's temp disk and using bandwidth before receiving a 413. Locally (bound to 127.0.0.1) this needs local access.
- **Remediation:** a small ASGI middleware that rejects requests whose `Content-Length` exceeds the limit plus multipart overhead, and stops reading chunked bodies once they exceed it, returning the same 413 message. In production also set the reverse proxy's body limit. Regression tests: an oversized `Content-Length` is refused with 413 before the handler runs; a chunked body over the limit is refused; normal uploads are unaffected.

### F5. No authentication or authorization (Critical for network deployment; Info for local use; confirmed)

- **Evidence:** no auth middleware or dependencies (`backend/app/main.py`, `backend/app/api/*.py`). `GET /api/datasets` lists every dataset; `GET .../analyses/{id}` returns full results (figures, product names, line numbers); `DELETE /api/datasets/{id}` deletes anything. IDs are sequential (`AUTOINCREMENT`).
- **Impact:** anyone who can reach the backend can read all saved analyses and delete all data. The README's commands bind to `127.0.0.1` (Uvicorn default), which limits this to the local machine today.
- **Remediation:** a deployment blocker. Options range from "keep it local only" (document and enforce binding) to a single shared access token, to real accounts with per-user datasets. **This is an architectural decision; not implemented in this milestone.**

### F6. No production serving story (Medium, confirmed)

- **Evidence:** the frontend calls relative `/api/...` URLs (`frontend/src/api/http.ts`); only the Vite **dev** server proxies `/api` (`frontend/vite.config.ts`, `server.proxy`); `vite preview` has no proxy; FastAPI serves no static files; no CORS middleware is configured.
- **Impact:** `npm run build` produces static files with no documented way to serve them next to the API. Serving them from another origin would fail without CORS.
- **Remediation:** document a same-origin setup (a reverse proxy such as Caddy or nginx serving `frontend/dist` and forwarding `/api` to Uvicorn), or optionally let FastAPI serve `dist`. Add CORS only if a separate origin is chosen, with an explicit allow-list.

### F7. Repeated work and high memory per parse (Medium, confirmed)

- **Evidence:** in-memory mode uploads and parses the file six times; saved mode re-reads, re-hashes, and re-parses it for each of five analyses; insights re-runs the trends and performance calculations. Measured for a 10 MB file of small cells (about 1 million rows x 5 columns): `parse_csv` holds **about 250 MB** of Python objects (peak about 300 MB), and `profile_csv` takes about 12.6 s of CPU.
- **Impact:** one upload can need well over 1 GB at peak (five parallel analyses, each with its own parsed copy plus DuckDB), estimated from the per-parse measurement; concurrent users multiply it. Response times grow with file size.
- **Remediation (architectural, proposal):** a single "analyze" request that parses once and returns every section (and records them in one transaction), or a server-side parsed-file cache for saved datasets. Not implemented in this milestone.

### F8. No DuckDB limits, server-side timeouts, or rate limits (Medium; confirmed in code; load impact needs verification)

- **Evidence:** `duckdb.connect(":memory:")` uses DuckDB defaults (all cores, memory limit about 80% of RAM per connection) (`backend/app/analytics/duckdb_loader.py`). No request timeout on the server; the frontend aborts after 120 s, but the server keeps computing. No rate limiting. The thread pool defaults to 40 workers.
- **Remediation (proposal):** `DUCKDB_THREADS` and `DUCKDB_MEMORY_LIMIT` settings with conservative defaults; rate limiting at the reverse proxy.

### F9. API docs always on (Low, confirmed)

- **Evidence:** `FastAPI(...)` in `backend/app/main.py` keeps `/docs`, `/redoc`, and `/openapi.json`; `APP_ENV` is only echoed by `/api/health`.
- **Remediation (proposal):** disable the docs when `APP_ENV=production`.

### F10. History grows without bound; listing parses every result (Low, confirmed)

- **Evidence:** saving a file that already exists still records five new analyses per upload (`useCsvAnalysis.ts` runs every step; the service returns the existing dataset). `list_analyses` validates every stored `result_json` to build highlights (`backend/app/datasets/service.py` `_analysis_summary` → `_record`). No pagination.
- **Remediation (proposal):** store highlights in a column at insert time, paginate history, and optionally skip re-running analyses for an unchanged duplicate upload.

### F11. Migrations run on every database open (Low, confirmed)

- **Evidence:** `open_database` → `migrate(connection, load_migrations(...))` reads every migration file and checks the version on each request (`backend/app/storage/database.py`). Correct and concurrency-safe (`BEGIN IMMEDIATE` plus re-check), but wasteful.
- **Remediation (proposal):** migrate once at startup (FastAPI lifespan) and skip afterwards.

### F12. Liveness only, no readiness check (Low, confirmed)

- **Evidence:** `GET /api/health` returns static values (`backend/app/api/health.py`); it does not check that `DATA_DIR` is writable or that the database opens and is migrated.
- **Remediation (proposal):** `GET /api/health/ready` that opens the database and checks the data directory.

### F13. Dependency hygiene (Low, confirmed)

- **Evidence:** `backend/requirements.txt` uses version ranges with no lock file and includes test tools (`pytest`, `httpx2`). `npm audit`: **0 vulnerabilities** (run during this audit). No Python vulnerability scan was run (`pip-audit` is not installed).
- **Remediation (proposal):** split `requirements-dev.txt`, pin runtime versions (or a lock file), run `pip-audit` in CI.

### F14. Narration in-flight guard is per process (Low, confirmed)

- **Evidence:** `_in_flight` is a module-level set (`backend/app/narration/service.py`). With several Uvicorn workers, two narrations of the same analysis can run at once (both are recorded; no data corruption).
- **Remediation:** document single-worker use, or use a database lock if multiple workers are needed.

### F17. DuckDB spills user data into the server's working directory (Medium, confirmed in Phase C)

- **Evidence:** DuckDB's default `temp_directory` is `.tmp` relative to the working directory. Experiment: a connection with a 16 MB limit created `.tmp` in the current directory while spilling a 64 MB table. With the old defaults (about 80% of RAM) spilling was unlikely; with a conservative limit it becomes normal. Started from `backend/`, that is `backend/.tmp`: inside the repository and OneDrive, and not git-ignored.
- **Impact:** copies of uploaded data on disk outside `DATA_DIR`, possibly synced or committed, and never cleaned up by the app.
- **Remediation:** point `temp_directory` at the request's own temporary directory, which is removed after the analysis.

### F18. DuckDB progress bar in server output (Low, confirmed in Phase C)

- **Evidence:** a long query (3 million rows) printed a progress bar to standard output in the experiment.
- **Remediation:** `SET enable_progress_bar = false` on every analysis connection.

### F15. Data at rest is unencrypted, with no retention policy (Info, confirmed)

- **Evidence:** raw CSV files, results, and rejected model text (kept for audit) are stored as plain files and SQLite rows under `DATA_DIR`; deletion is manual per dataset.
- **Remediation:** document it; rely on disk encryption and access control on the host.

---

## 4. Verified as sound (no change needed)

| Area | Evidence |
| --- | --- |
| SQL injection | Column names never enter SQL: generated identifiers `c0, c1, ...` checked by `_SAFE_IDENTIFIER` (`duckdb_loader.py`); working-table and role names are fixed strings; values and patterns are bound parameters; SQLite queries are parameterized (`repository.py`). Tests use hostile column names and labels. |
| Path traversal and filenames | Stored files are named by SHA-256 (`FileStore.path_for` rejects anything else); uploaded names are labels only (`display_name` strips folders, caps length). |
| Temporary files | DuckDB load uses `TemporaryDirectory` (removed even on error); FastAPI closes upload files after the response. |
| Encoding and malformed CSV | UTF-8 (BOM accepted), NUL bytes rejected, ragged rows rejected with the line number, blank and duplicate headers rejected, Python's 131,072-character field limit applies. |
| Decompression bombs | No compressed formats are accepted, and request bodies are never decompressed. |
| Error responses | `debug` is off, so unhandled errors return a plain 500 without a stack trace; handled errors carry messages written in code (no paths or internals). The frontend shows a generic message for any 5xx. |
| Logging | No CSV content, findings, or secrets are logged (one `logger.exception` logs a file hash). |
| Secrets | `.env` and `.env.*` are git-ignored (only `.env.example` is tracked, with no values); `GEMINI_API_KEY` is a `SecretStr` and unused; the narrator status returns no URLs or keys. |
| Narration content | Only findings text is sent; output is validated (numbers, quoted names, causes, predictions, markup, length); rejected text is never returned; every attempt is recorded. Covered by tests with a fake narrator. Real-model behaviour is **not** validated. |
| Atomicity | Analyses are computed first and inserted in one transaction; a deleted dataset during an analysis or narration maps to 404 without partial rows. Duplicate concurrent saves are handled (`UNIQUE` hash + `IntegrityError`). |
| Frontend dependencies | `npm audit`: 0 vulnerabilities. |

---

## 5. Fixes applied (Phase C)

Each fix has regression tests that were seen failing before the fix (or under a deliberate mutation of it), and passing after.

| Finding | Change | Files | Regression tests |
| --- | --- | --- | --- |
| F1 | The Ollama adapter uses its own `urllib` opener with `ProxyHandler({})` (no proxies from `HTTP_PROXY`, `http_proxy`, or the system) and a redirect handler that refuses every redirect with a `NarratorError`. | `backend/app/narration/ollama.py` | `test_ollama_narrator.py`: `test_proxy_settings_are_ignored` (4 variables; reloads the module as a freshly started server would) and `test_redirects_are_refused` (301, 302, 303, 307, 308; the redirect target is never contacted). |
| F2 | Duplicate headers are found with one `Counter` pass (`duplicate_names`); messages are unchanged. | `backend/app/ingestion/csv_parser.py` | `test_csv_limits.py`: 200,000 names checked in under 1 s; the message for `b,a,b,a,c` is exactly as before. |
| F16 | Files with more than 1,000 columns are rejected with 422 and "The file has N columns. InsightFlow accepts at most 1,000 columns." The count is checked before anything else in the header. | `backend/app/ingestion/csv_parser.py` | `test_csv_limits.py`: 1,000 accepted, 1,001 rejected with the exact message, a 200,000-column header rejected in under 2 s, the limit checked before duplicates. |
| F3 | The six in-memory endpoints parse with `await run_in_threadpool(parse_or_422, content)`. | `backend/app/api/uploads.py` | `test_request_limits.py`: parsing runs in a worker thread for all six endpoints; `/api/health` answers in under 0.5 s while an upload is being parsed. |
| F4 | `RequestBodyLimit`, a pure ASGI middleware: a declared `Content-Length` over `MAX_UPLOAD_MB` plus 256 KB is answered with 413 before any body is read; a body without a length is counted as it arrives and cut off with 413 once it passes the limit (FastAPI re-raises the `HTTPException` raised while reading). Files just over the upload limit still reach the route's own check, so the message is the same. | `backend/app/api/request_limits.py`, `backend/app/main.py` | `test_request_limits.py`: a 50 MB declared length is refused with 0 body chunks read; a 5 MB streamed body is cut off after at most 25 of 81 chunks; small and large overshoots get the same 413 message; normal uploads and saves still work. |
| F9 | `create_app()` sets `docs_url`, `redoc_url`, and `openapi_url` to `None` when `APP_ENV=production`. | `backend/app/main.py` | `test_production_config.py`: `/docs`, `/redoc`, `/openapi.json`, and `/docs/oauth2-redirect` return 404 in production and are available otherwise; the API still answers. |
| F12 | `GET /api/health/ready` opens the database (the same path every request uses, which applies pending migrations), runs `SELECT 1`, compares the schema version with the migrations, and creates then removes a uniquely named probe file in `DATA_DIR`. 200 when ready, 503 with the failed checks otherwise. Answers never contain server paths; details go to the server log. | `backend/app/api/health.py` | `test_production_config.py`: ready with the right schema version and user files untouched and no probe left behind; 503 when `DATA_DIR` is a file and when the database path is a directory, with no paths in the answer. |
| F8 (part), F17, F18 | Every analysis connection gets `threads = DUCKDB_THREADS` (default 2, 1 to 64), `memory_limit = DUCKDB_MEMORY_LIMIT` (default `1GB`, at least `64MB`; validated), `temp_directory` inside the request's temporary directory, and no progress bar. An analysis that still runs out of memory returns 413 with a clear message instead of a 500. | `backend/app/config.py`, `backend/app/analytics/duckdb_loader.py`, `backend/app/main.py`, `backend/.env.example` | `test_production_config.py`: defaults, invalid values refused (including below 64 MB), the configured values are what DuckDB reports, a 16 MB limit really raises `OutOfMemoryException`, spills stay in (and are removed with) the request's directory and never create `.tmp` in the working directory, no progress bar, and the 413 message. |

Documentation: `README.md` (readiness check, docs off in production, the 1,000-column limit, the 413 cases, the DuckDB settings, and a pointer to this audit) and `backend/.env.example` (`DUCKDB_THREADS`, `DUCKDB_MEMORY_LIMIT`, and what `APP_ENV=production` and `MAX_UPLOAD_MB` now do).

**Side effect to know:** `create_app()` now reads the settings when the app module is imported, so an invalid value in `backend/.env` stops the server at startup instead of failing the first request.

### Verified against a real server (Uvicorn, scratch data directory)

| Check | Before | After |
| --- | --- | --- |
| `/api/health` while a 9 MB in-memory upload is parsed | 2.0 s (idle: 0.06 s) | 0.46 s (idle: 0.13 s) |
| Request declaring 50 MB, no body sent | Not tested before | `413 Content Too Large` after 0.002 s |
| Chunked 40 MB stream, no length | Whole body accepted, then 413 | `413` once the client had sent 10.3 MB (limit 10 MB + 0.25 MB) |
| All six analyses on a realistic 9.5 MB file (218,742 rows) with the new DuckDB defaults | n/a | All 200: 1.1 s to 6.0 s each |
| Five analyses of that file at once (as the UI runs them) | n/a | All 200 (11.4 s to 17.6 s); `/api/health` 1.6 s during the burst |

### What is still not fixed

- **F3 is only partly fixed.** Parsing no longer runs on the event loop, but parsing and profiling are pure Python and hold the GIL, so other requests still slow down while large files are processed (0.46 s for one upload, 1.6 s for five at once). Removing that needs a process pool or a single-pass analysis (F7), which is an architectural change.
- **F4:** the limit is enforced by the app while the body arrives. Up to about 10.25 MB per request can still be written to the temporary directory before the cut-off, and many concurrent requests multiply that. A body limit at the reverse proxy remains a deployment requirement.
- F5, F6, F7, F8 (timeouts, rate limits), F10, F11, F13, F14, F15: open, as described in section 3.

## 6. Unknowns and items needing verification

- The deployment target (single machine, container, cloud host) is not defined; it determines the auth, proxy, storage, and backup requirements.
- Behaviour under real multi-user load was not tested; the concurrency numbers above are five requests from one machine.
- Multiple Uvicorn workers, and SQLite on network storage, are untested.
- Python dependencies were not scanned for known vulnerabilities (`pip-audit` is not installed).
- The Ollama narrator has not been run against a real model.
- Whether 1 GB per DuckDB connection suits the intended host depends on its memory and on how many analyses run at once (five per upload in the current UI).

## 7. Deployment-blocker checklist

- [ ] **Access control (F5):** keep the backend bound to `127.0.0.1`, or add authentication before exposing it on any network. *Blocker.*
- [x] **Narrator egress (F1):** fixed and tested. The narrator stays off by default.
- [x] **Quadratic header check (F2)** and **column limit (F16):** fixed and tested.
- [ ] **Event-loop and GIL contention (F3, F7):** parsing moved off the event loop; heavy files still slow other requests. Acceptable for one user; needs a process pool or single-pass analysis for several.
- [x] **Body size limit in the app (F4):** enforced while receiving and verified on a real server.
- [ ] **Body size limit at the reverse proxy (F4):** still required in production.
- [ ] **Serving (F6):** a documented same-origin setup for `frontend/dist` and `/api`; CORS only if needed, with an allow-list. *Blocker.*
- [ ] **Storage:** `DATA_DIR` on persistent, backed-up, non-synced storage; disk encryption and permissions on the host (F15).
- [x] **DuckDB limits (F8, F17, F18):** threads, memory, spill location, and output configured and tested.
- [ ] **Timeouts and rate limits (F8):** at the reverse proxy.
- [x] **Readiness (F12):** `/api/health/ready`.
- [x] **Docs off in production (F9):** with `APP_ENV=production`.
- [ ] **Operations:** start command without `--reload`; a single worker (F14) or a database-backed narration lock; startup migrations (F11); history pagination (F10).
- [ ] **Dependencies (F13):** split dev requirements, pin runtime versions, run `pip-audit`.

## 8. Phase A verification log

| Command / experiment | Result |
| --- | --- |
| `git status -sb`, `git log --oneline -4` | `master...insightflow/master`, clean; latest `fb82dcd` |
| Tracked sensitive files (`git ls-files` for `.env`, `.db`, `dist/`) | None |
| Duplicate-header timing (2k / 4k / 8k columns) | 0.08 s / 0.40 s / 1.46 s |
| `parse_csv` on a 10 MB, 1,048,576-row file | 3.10 s; about 250 MB held (300 MB peak, traced run) |
| `profile_csv` on the same rows | 12.63 s |
| Retail metrics (DuckDB load + queries) on the same rows | 2.34 s |
| `/api/health` latency alone vs during a 9 MB in-memory upload (scratch server, port 8011) | 0.06 s vs 2.0 s |
| Narrator with `HTTP_PROXY` set to a local fake proxy | Both requests (including the 158-byte prompt) reached the proxy |
| `urllib` redirect rules (Python 3.14 source) | GET redirects followed; POST 301-303 re-sent as GET without body; 307/308 POST refused |
| `npm audit` (frontend) | 0 vulnerabilities |
| Grep for CORS, `debug`, docs settings | None configured (FastAPI defaults) |

## 9. Phase D verification log (final code)

| Command (from the folder shown) | Result |
| --- | --- |
| `backend/`: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` | **407 passed** (was 364 before this milestone) |
| `backend/`: `pytest tests/test_csv_limits.py tests/test_request_limits.py tests/test_production_config.py tests/test_ollama_narrator.py tests/test_narration.py` | 84 passed |
| `frontend/`: `npm test` | 14 files, **139 passed** |
| `frontend/`: `npm run lint` | exit 0 |
| `frontend/`: `npx tsc -b` | exit 0 |
| `frontend/`: `npm run build` | built, exit 0 |
| `frontend/`: `npm audit` | 0 vulnerabilities |
| repository: `git diff --check` | exit 0 |
| Mutation checks: each fix disabled in turn (no proxy handler, no redirect handler, one endpoint parsing on the event loop, no length precheck, no streaming count, probe file not removed, no spill directory) | Each was caught by at least one failing test; the files were restored and compared byte for byte |
| Secret scan of the diff and new files; generated-file scan of the working tree | Nothing found |

The proxy test first passed even without the fix: `urllib` reads proxy variables when an opener is built, and the module's opener was built before the test set the variable. The test now reloads the module after setting it, as a server started with the variable would, and fails without the fix.

## 10. Milestone 8.1 review (before commit)

An independent pass over the working tree before committing. Code checked against this document; experiments in a scratch directory.

| Check | Evidence | Result |
| --- | --- | --- |
| Branch, HEAD, staging | `git branch --show-current`, `git rev-parse --short HEAD`, `git diff --cached --stat` | `master`, `fb82dcd`, nothing staged |
| Only Milestone 8 files changed | `git status --short --untracked-files=all` | 10 modified + 5 new files, all listed in this document; no other changes |
| No `.env`, credentials, databases, spill folders, or build output | `.env` absent (and ignored by `.gitignore:2`); no `.tmp`, `*.duckdb*`, or `insightflow.db` in the repository; secret-pattern scan of the diff and new files | None found |
| Request cleanup after a 413 cut-off | A 5 MB chunked body sent through the app with `MAX_UPLOAD_MB=1`; system temp directory listed during and after | A spooled file existed about 1.2 MB in (`tmp9pco98n3`) and was gone right after the 413, before garbage collection. Starlette does not close it explicitly on this error; it is removed when the request's objects are released (immediately under CPython's reference counting). |
| Leftover per-request directories | `insightflow-*` in the system temp directory after all test and server runs | None (the one match, `insightflow-mailmap.txt`, is a 67-byte file from the Git author rewrite, not created by the app) |
| Only one outbound HTTP client | Search of `backend/app` for `urlopen`, `requests`, `httpx`, `http.client` | Only the narrator's `_OPENER` (no proxies, no redirects) |
| DuckDB memory values: startup validation vs DuckDB | 18 values tried: everything `Settings` accepts (for example `1GB`, `1 GB`, `1.5GB`, `512MiB`, `1gb`, `2TB`, `64000000B`) is accepted by DuckDB; `63MB`, `10KB`, `1,000MB`, `1e9B`, and `1G` are refused at startup | Consistent; invalid values stop the server at startup because `create_app()` reads the settings on import |
| `create_app(settings)` docstring | Claimed every route uses `settings`; DuckDB limits are read from `get_settings()` | **Corrected** (comment only, no behaviour change) |
| This document's lifecycle section | Described the Phase A behaviour as current | **Corrected** (section 2) |
