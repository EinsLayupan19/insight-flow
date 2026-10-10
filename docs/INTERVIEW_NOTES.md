# Interview Notes

Short notes to practice explaining InsightFlow AI out loud. Only claim what you can explain yourself.

---

## Phase 1 — Project foundation

### 1. Health check endpoint (`GET /api/health`)

- **Problem it solves:** Gives the frontend, the developer, and later a deployment platform a quick way to confirm the API is running.
- **Key concept:** A small, read-only endpoint that returns a typed response (Pydantic `HealthResponse`).
- **Why this implementation:** Settings are injected with FastAPI's `Depends(get_settings)`, so tests can swap in different settings without touching real environment variables.
- **Likely question:** *"How did you test your API?"*
- **Sample answer:** "I used Pytest with FastAPI's TestClient, which calls the app in memory without starting a real server. I tested the happy path, a 404 for an unknown route, and that the health response never includes the API key. I used dependency overrides to inject test settings."
- **Trade-off:** It only shows that the API process is alive. It doesn't yet check dependencies like the database. A deeper "readiness" check could come later.

### 2. Safe configuration and secrets

- **Problem it solves:** Keeps API keys and machine-specific values out of the code and out of Git.
- **Key concept:** Environment variables loaded by `pydantic-settings` from `backend/.env`. `.env` is git-ignored, and `.env.example` documents the variable names.
- **Why this implementation:** One `Settings` class validates types in a single place (for example, `app_env` must be development, test, or production). `SecretStr` hides the key if settings get printed.
- **Likely question:** *"How do you handle API keys in a web app?"*
- **Sample answer:** "Keys only live on the backend, in an environment file that's excluded from Git. The frontend never sees them. Anything shipped to the browser is public, so the browser asks my backend, and the backend talks to the AI provider."
- **Trade-off:** `.env` files are fine for local development. Production would use the hosting platform's secret manager.

### 3. Frontend → backend connection status

- **Problem it solves:** Shows right away whether the UI can reach the API, with a clear fix if it can't.
- **Key concept:** The Vite dev proxy forwards `/api/*` from the frontend server to FastAPI. The UI is driven by three states: `checking`, `connected`, and `error`.
- **Why this implementation:** The proxy avoids CORS setup and keeps the backend URL out of frontend code. Splitting the code into API client → hook → component keeps each file small and single-purpose.
- **Likely question:** *"Why use a proxy instead of calling the backend URL directly?"*
- **Sample answer:** "In development the frontend and backend run on different ports, which normally means configuring CORS. With Vite's proxy, the browser only talks to one origin, and Vite forwards API calls. It also mirrors a common production setup where both sit behind the same domain."
- **Trade-off:** The Vite proxy only exists in development. Production will need a real reverse proxy or a CORS configuration.

---

## Phase 2 — CSV ingestion

### 4. CSV upload and validation (`POST /api/uploads/csv`)

- **Problem it solves:** Analysts need to bring their own data in, and bad files must be caught *before* analysis, not discovered as wrong numbers later.
- **Key concept:** Two layers of validation. The **route** checks the request (file present, `.csv` extension, size limit). The **parser** (`app/ingestion/csv_parser.py`) checks the content (UTF-8, unique non-blank headers, every row the same width). Each failure maps to a specific HTTP status: 400 missing, 415 wrong type, 413 too large, 422 unreadable content.
- **Why this implementation:** I used Python's built-in `csv` module instead of pandas for this step because pandas silently "fixes" problems. It fills short rows with blanks and renames duplicate columns (`price` → `price.1`). For an evidence-first tool, I'd rather reject an ambiguous file with a clear message, like "Line 3 has 1 values, but the header has 2 columns." The parser has no FastAPI code, so I could unit-test it with plain bytes.
- **Likely question:** *"How do you handle messy or invalid data files?"*
- **Sample answer:** "I validate at the boundary, before anything gets analyzed. My upload endpoint checks the request first, like file type and size, and then a separate parser checks the structure: encoding, duplicate or missing headers, and rows with the wrong number of values. Each problem returns a specific status code and a message that tells the user how to fix it. One thing I found while testing: Python's csv module accepts null bytes, which usually means a binary or UTF-16 file was renamed to .csv, so I added an explicit check."
- **Trade-off (CSV upload):** It only understands comma-delimited UTF-8. A semicolon-separated file is read as one wide column, not rejected. The whole file is also held in memory, so there's a size cap (10 MB by default). The file isn't stored yet, so every upload is a one-off check.

### 5. Data-quality profiler (`POST /api/uploads/csv/profile`)

- **Problem it solves:** Before trusting any number from a dataset, an analyst needs to know what's wrong with it: gaps, repeated rows, and values in the wrong format.
- **Key concept:** A *read-only* profile. For each column, it counts missing cells (empty or spaces only), counts how many values look like each type, infers the column's type by majority (more than half of non-missing values), and counts mismatches with line-numbered examples. It also counts exact duplicate rows. Every metric's definition is returned inside the report.
- **Why this implementation:** I wrote the type rules myself (regular expressions plus real date parsing) instead of relying on pandas' automatic inference, so every rule is explicit and documented in the response. Placeholders like "N/A" are deliberately *not* treated as missing. They show up as type mismatches, so the analyst decides what they mean and the tool doesn't guess. A test confirms the profiler never modifies the data.
- **Likely question:** *"What do you check first when you get a new dataset?"*
- **Sample answer:** "I profile it before analyzing it. In my project, the profiler reports missing values per column, exact duplicate rows, and each column's inferred type, with a count of values that don't fit, like 'N/A' in a quantity column or an impossible date like February 30th. It shows line numbers so you can find the problem in the file. It only reports. It doesn't fix anything automatically, because deciding whether a duplicate is an error or two real identical orders is a business decision."
- **Trade-off:** Duplicates are exact text matches, so "North" and "north " count as different rows. Dates must be YYYY-MM-DD, because 05/01/2026 is ambiguous (US vs. EU) and is reported as text. It's pure Python: about 3 seconds for a 10 MB file, so I run it in a worker thread to keep the server responsive. DuckDB will be much faster when we need scale.
