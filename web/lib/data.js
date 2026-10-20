// Backend data layer. In production (DATABASE_URL set) it reads Postgres; in
// local dev it falls back to the committed JSON snapshot. Both return the SAME
// shape so the dashboard renders identically. The deployed backend therefore
// retrieves saved analysis from the database and serves it to the dashboard.
import fs from "node:fs";
import path from "node:path";

let cache = null;

function readSnapshotFile() {
  const p = path.join(process.cwd(), "data", "snapshot.json");
  return JSON.parse(fs.readFileSync(p, "utf-8"));
}

function dbUrl() {
  return process.env.DATABASE_URL || process.env.POSTGRES_URL ||
    process.env.POSTGRES_PRISMA_URL || process.env.POSTGRES_URL_NON_POOLING || "";
}

async function readFromPostgres() {
  const { Pool } = await import("pg");
  const url = dbUrl();
  const pool = new Pool({
    connectionString: url,
    max: 2,
    ssl: /neon\.tech|vercel|supabase|render\.com|sslmode=require/.test(url)
      ? { rejectUnauthorized: false } : undefined,
  });
  try {
    const overview = (await pool.query("select data from overview where id=1")).rows[0]?.data ?? {};
    const ranking = (await pool.query(
      "select rank, issue_id, title, complaint_count, severity_sum, mean_severity, priority_score from ranking order by rank"
    )).rows;
    const rec = (await pool.query("select data from recommendation where id=1")).rows[0]?.data ?? null;
    const memberRows = (await pool.query(
      "select issue_id, title, review_id, severity, intent, sentiment, quote from issue_members order by issue_id, severity desc"
    )).rows;
    const issues = {};
    for (const m of memberRows) {
      if (!issues[m.issue_id]) issues[m.issue_id] = { issue_id: m.issue_id, title: m.title, members: [] };
      issues[m.issue_id].members.push({
        review_id: m.review_id, severity: m.severity, intent: m.intent,
        sentiment: m.sentiment, quote: m.quote,
      });
    }
    const meta = (await pool.query("select data from run_meta where id=1")).rows[0]?.data ?? {};
    return { generated_at: meta.generated_at, overview, ranking, recommendation: rec, issues };
  } finally {
    await pool.end();
  }
}

export async function getData() {
  if (cache) return cache;
  if (dbUrl()) {
    try {
      cache = await readFromPostgres();
      return cache;
    } catch (e) {
      // Fall back to the committed snapshot if the DB is unreachable/empty.
      console.error("Postgres read failed, using snapshot:", e.message);
    }
  }
  cache = readSnapshotFile();
  return cache;
}

export function dataSource() {
  return dbUrl() ? "postgres" : "snapshot";
}
