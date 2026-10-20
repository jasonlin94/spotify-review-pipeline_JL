-- Postgres schema for the deployed dashboard backend.
-- The backend reads these tables; db/seed.mjs loads them from web/data/snapshot.json
-- (which db/make_snapshot.py builds from the saved analysis outputs).

CREATE TABLE IF NOT EXISTS overview (
  id        INT PRIMARY KEY DEFAULT 1,
  data      JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS run_meta (
  id        INT PRIMARY KEY DEFAULT 1,
  data      JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendation (
  id        INT PRIMARY KEY DEFAULT 1,
  data      JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS ranking (
  rank            INT PRIMARY KEY,
  issue_id        TEXT NOT NULL,
  title           TEXT,
  complaint_count INT NOT NULL,
  severity_sum    INT NOT NULL,
  mean_severity   TEXT NOT NULL,   -- exact 6dp string from the deterministic ranking
  priority_score  INT NOT NULL
);

CREATE TABLE IF NOT EXISTS issue_members (
  issue_id   TEXT NOT NULL,
  review_id  TEXT NOT NULL,
  title      TEXT,
  severity   INT NOT NULL,
  intent     TEXT NOT NULL,
  sentiment  REAL NOT NULL,
  quote      TEXT NOT NULL,
  PRIMARY KEY (issue_id, review_id)
);

CREATE INDEX IF NOT EXISTS idx_members_issue ON issue_members (issue_id, severity DESC);
