"use client";
import { useEffect, useState } from "react";

const TOPIC_LABEL = {
  access: "Access (login/account)", usability: "Usability (controls/ads)",
  playback: "Playback (failures/crashes)", downloads: "Downloads (offline)",
  catalog: "Catalog (search/content)", billing: "Billing (charges/premium)",
  support: "Support", other: "Other",
};

function num(n) { return n == null ? "—" : Number(n).toLocaleString(); }

export default function Dashboard() {
  const [ov, setOv] = useState(null);
  const [ranking, setRanking] = useState([]);
  const [rec, setRec] = useState(null);
  const [sel, setSel] = useState(null);
  const [issue, setIssue] = useState(null);

  useEffect(() => {
    fetch("/api/overview").then((r) => r.json()).then(setOv);
    fetch("/api/ranking").then((r) => r.json()).then((d) => setRanking(d.ranking || []));
    fetch("/api/recommendation").then((r) => r.json()).then((d) => setRec(d.recommendation));
  }, []);

  useEffect(() => {
    if (!sel) return;
    setIssue(null);
    fetch(`/api/issues/${sel}`).then((r) => r.json()).then((d) => setIssue(d.issue));
  }, [sel]);

  const o = ov?.overview || {};
  const maxScore = ranking.length ? ranking[0].priority_score : 1;

  return (
    <div className="wrap">
      <header>
        <h1>
          Spotify Reviews — Product Priority Dashboard
          {ov && <span className="badge">source: {ov.source}</span>}
        </h1>
        <div className="sub">
          Auditable analysis of real Spotify reviews. Every number traces to saved
          deterministic calculations and source reviews.
          {ov?.generated_at && ` · generated ${new Date(ov.generated_at).toLocaleString()}`}
        </div>
      </header>

      {/* Overall metrics */}
      <section>
        <div className="grid">
          <div className="card"><div className="k">Reviews ingested</div>
            <div className="v">{num(o.rows_total)}</div></div>
          <div className="card"><div className="k">Classified</div>
            <div className="v">{num(o.completed)} <small>completed</small></div></div>
          <div className="card"><div className="k">Quarantined</div>
            <div className="v">{num(o.quarantined ?? o.rows_empty)}</div></div>
          <div className="card"><div className="k">Distinct texts</div>
            <div className="v">{num(o.distinct_nonempty_texts)}</div></div>
          <div className="card"><div className="k">Exact-text reuse</div>
            <div className="v">{num(o.exact_text_reuse_savings)} <small>saved</small></div></div>
        </div>
        <div className="muted">Model: {o.model || "—"}</div>
      </section>

      {/* AI recommendation */}
      <section>
        <h2>AI-generated recommendation</h2>
        {!rec ? <div className="loading">Loading…</div> : (
          <div className="rec">
            <h3>{TOPIC_LABEL[rec.recommendation_issue_id] || rec.recommendation_issue_id}</h3>
            <div className="why"><strong>{rec.headline}</strong></div>
            <div className="why" style={{ marginTop: 8 }}>{rec.rationale}</div>
            <div className="chips">
              {(rec.supporting_claim_ids || []).map((c) => <span className="chip" key={c}>claim {c}</span>)}
              {(rec.representative_review_ids || []).map((r) => (
                <span className="chip" key={r} title="source review id">{r.slice(0, 8)}…</span>
              ))}
            </div>
            {rec.limitations && <div className="muted" style={{ marginTop: 10 }}>⚠ {rec.limitations}</div>}
          </div>
        )}
      </section>

      {/* Issue ranking */}
      <section>
        <h2>Issue ranking <span className="muted">(priority = severity_sum = count × mean severity)</span></h2>
        <table>
          <thead><tr>
            <th>#</th><th>Issue</th><th>Complaints</th><th>Mean sev</th><th>Priority</th><th></th>
          </tr></thead>
          <tbody>
            {ranking.map((r) => (
              <tr key={r.issue_id} className={sel === r.issue_id ? "sel" : ""}
                  onClick={() => setSel(r.issue_id)}>
                <td>{r.rank}</td>
                <td><strong>{r.issue_id}</strong><div className="muted">{r.title}</div></td>
                <td>{num(r.complaint_count)}</td>
                <td>{r.mean_severity}</td>
                <td>{num(r.priority_score)}</td>
                <td><div className="barwrap"><div className="bar"
                  style={{ width: `${Math.max(4, 120 * r.priority_score / maxScore)}px` }} /></div></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="muted" style={{ marginTop: 6 }}>Click an issue to see its source-review evidence.</div>
      </section>

      {/* Issue drill-down = traceable evidence */}
      {sel && (
        <section>
          <h2>Evidence for “{sel}” {issue && <span className="muted">({issue.members.length} shown)</span>}</h2>
          {!issue ? <div className="loading">Loading evidence…</div> : (
            <div className="members">
              {issue.members.map((m) => (
                <div className="member" key={m.review_id}>
                  <div className="meta">
                    <span className={`sevpill s${m.severity}`}>S{m.severity}</span>{" "}
                    {m.intent} · sentiment {m.sentiment} · review_id {m.review_id}
                  </div>
                  <div className="q">“{m.quote}”</div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
