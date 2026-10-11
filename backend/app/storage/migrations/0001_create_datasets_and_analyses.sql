-- Saved datasets: one row per distinct uploaded file content.
-- AUTOINCREMENT means a deleted dataset's id is never reused, so an old link
-- answers "not found" instead of showing a different dataset.
CREATE TABLE datasets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT    NOT NULL,             -- name as uploaded; a label only, never used as a path
    sha256        TEXT    NOT NULL UNIQUE,      -- hash of the file content; detects duplicate uploads
    size_bytes    INTEGER NOT NULL CHECK (size_bytes > 0),
    row_count     INTEGER NOT NULL CHECK (row_count > 0),
    column_count  INTEGER NOT NULL CHECK (column_count > 0),
    columns_json  TEXT    NOT NULL,             -- JSON array of column names, in file order
    stored_file   TEXT    NOT NULL,             -- name of the stored copy inside the uploads directory
    created_at    TEXT    NOT NULL              -- UTC, ISO 8601
);

-- Analysis history: every data-quality check or metrics calculation run on a saved dataset.
-- Deleting a dataset deletes its history (ON DELETE CASCADE).
CREATE TABLE analyses (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id       INTEGER NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    kind             TEXT    NOT NULL CHECK (kind IN ('profile', 'metrics')),
    parameters_json  TEXT    NOT NULL,          -- inputs, e.g. the column mapping used for metrics
    result_json      TEXT    NOT NULL,          -- the result exactly as the API returned it
    app_version      TEXT    NOT NULL,          -- InsightFlow version whose rules produced the result
    created_at       TEXT    NOT NULL           -- UTC, ISO 8601
);

CREATE INDEX analyses_by_dataset ON analyses (dataset_id, created_at);
