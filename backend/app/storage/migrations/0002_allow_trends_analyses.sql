-- Allow a third analysis kind, 'trends' (sales trends by day, week, or month).
--
-- SQLite cannot change a CHECK constraint in place, so the analyses table is rebuilt:
-- create the new table, copy every row with its id, carry over the AUTOINCREMENT
-- counter (so ids of deleted analyses are still never reused), then swap the tables.
-- The runner applies this whole file in one transaction: if any step fails, nothing changes.
-- Only the analyses table changes. No other table references it, and its own foreign
-- key to datasets is unchanged.

CREATE TABLE analyses_new (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id       INTEGER NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    kind             TEXT    NOT NULL CHECK (kind IN ('profile', 'metrics', 'trends')),
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
