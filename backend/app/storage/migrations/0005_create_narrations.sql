-- Narrations: optional AI-written summaries of a recorded insights analysis, one row per attempt.
--
-- analysis_id deliberately has no foreign key. Adding an analysis kind rebuilds the analyses
-- table (see 0002-0004), and with foreign keys on, dropping it would delete every narration
-- through a cascade. Instead, narrations belong to their dataset (which is never rebuilt) and
-- are deleted with it; analyses are only ever deleted with their dataset too. The service
-- checks that analysis_id is an insights analysis of that dataset before recording anything.

CREATE TABLE narrations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id      INTEGER NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    analysis_id     INTEGER NOT NULL,           -- the insights analysis that was summarized
    provider        TEXT    NOT NULL,           -- e.g. ollama
    model           TEXT    NOT NULL,           -- e.g. llama3.2:3b
    prompt_version  TEXT    NOT NULL,           -- the wording of the instructions, e.g. narration-v1
    status          TEXT    NOT NULL CHECK (status IN ('accepted', 'rejected', 'failed')),
    text            TEXT    NOT NULL,           -- what is shown: the model's text only when accepted, else the template summary
    raw_text        TEXT,                       -- the model's reply, kept for audit only and never shown; NULL when it failed
    problems_json   TEXT    NOT NULL,           -- why the model's text was not used, as a JSON array
    created_at      TEXT    NOT NULL            -- UTC, ISO 8601
);

CREATE INDEX narrations_by_analysis ON narrations (dataset_id, analysis_id, created_at);
