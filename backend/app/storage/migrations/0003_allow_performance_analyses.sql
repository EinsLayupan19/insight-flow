-- Allow a fourth analysis kind, 'performance' (revenue, quantity, and orders by product and category).
--
-- Same steps as 0002: SQLite cannot change a CHECK constraint in place, so the analyses
-- table is rebuilt. Every row is copied with its id, the AUTOINCREMENT counter is carried
-- over (ids of deleted analyses are still never reused), and the index is recreated.
-- The runner applies this whole file in one transaction: if any step fails, nothing changes.

CREATE TABLE analyses_new (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id       INTEGER NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    kind             TEXT    NOT NULL CHECK (kind IN ('profile', 'metrics', 'trends', 'performance')),
    parameters_json  TEXT    NOT NULL,          -- inputs, e.g. the column mapping and, for trends, the grain
    result_json      TEXT    NOT NULL,          -- the result exactly as the API returned it
    app_version      TEXT    NOT NULL,          -- InsightFlow version whose rules produced the result
    created_at       TEXT    NOT NULL           -- UTC, ISO 8601
);

INSERT INTO analyses_new (id, dataset_id, kind, parameters_json, result_json, app_version, created_at)
SELECT id, dataset_id, kind, parameters_json, result_json, app_version, created_at FROM analyses ORDER BY id;

-- Copying rows sets the new counter to the highest copied id; the old counter may be higher.
DELETE FROM sqlite_sequence WHERE name = 'analyses_new';
INSERT INTO sqlite_sequence (name, seq) SELECT 'analyses_new', seq FROM sqlite_sequence WHERE name = 'analyses';

DROP TABLE analyses;  -- also drops its index and its counter row
ALTER TABLE analyses_new RENAME TO analyses;  -- also renames the counter row

CREATE INDEX analyses_by_dataset ON analyses (dataset_id, created_at);
