// Load web/data/snapshot.json into Postgres (the deployed backend then reads it).
// Usage:
//   DATABASE_URL=postgres://... node db/seed.mjs
// Applies db/schema.sql first, then upserts all rows. Idempotent.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, "..");

async function main() {
  const url = process.env.DATABASE_URL || process.env.POSTGRES_URL ||
    process.env.POSTGRES_PRISMA_URL || process.env.POSTGRES_URL_NON_POOLING;
  if (!url) {
    console.error("No DB URL. Set DATABASE_URL (or POSTGRES_URL). Example:\n" +
      "  DATABASE_URL=postgres://user:pass@host/db node db/seed.mjs");
    process.exit(1);
  }
  const snapshot = JSON.parse(
    fs.readFileSync(path.join(root, "web", "data", "snapshot.json"), "utf-8")
  );
  const schema = fs.readFileSync(path.join(__dirname, "schema.sql"), "utf-8");

  const pool = new pg.Pool({ connectionString: url, ssl: needSsl(url) });
  const c = await pool.connect();
  try {
    await c.query("begin");
    await c.query(schema);
    await c.query("truncate ranking, issue_members");
    await c.query(
      "insert into overview(id,data) values(1,$1) on conflict(id) do update set data=excluded.data",
      [snapshot.overview]
    );
    await c.query(
      "insert into run_meta(id,data) values(1,$1) on conflict(id) do update set data=excluded.data",
      [{ generated_at: snapshot.generated_at }]
    );
    await c.query(
      "insert into recommendation(id,data) values(1,$1) on conflict(id) do update set data=excluded.data",
      [snapshot.recommendation]
    );
    for (const r of snapshot.ranking) {
      await c.query(
        `insert into ranking(rank,issue_id,title,complaint_count,severity_sum,mean_severity,priority_score)
         values($1,$2,$3,$4,$5,$6,$7)`,
        [r.rank, r.issue_id, r.title, r.complaint_count, r.severity_sum, r.mean_severity, r.priority_score]
      );
    }
    let members = 0;
    for (const iid of Object.keys(snapshot.issues)) {
      const issue = snapshot.issues[iid];
      for (const m of issue.members) {
        await c.query(
          `insert into issue_members(issue_id,review_id,title,severity,intent,sentiment,quote)
           values($1,$2,$3,$4,$5,$6,$7) on conflict(issue_id,review_id) do nothing`,
          [iid, m.review_id, issue.title, m.severity, m.intent, m.sentiment, m.quote]
        );
        members++;
      }
    }
    await c.query("commit");
    console.log(`Seeded: ${snapshot.ranking.length} ranked issues, ${members} issue members.`);
  } catch (e) {
    await c.query("rollback");
    throw e;
  } finally {
    c.release();
    await pool.end();
  }
}

function needSsl(url) {
  return /\bsslmode=require\b/.test(url) || /neon\.tech|vercel|supabase|render\.com/.test(url)
    ? { rejectUnauthorized: false } : false;
}

main().catch((e) => { console.error(e); process.exit(1); });
