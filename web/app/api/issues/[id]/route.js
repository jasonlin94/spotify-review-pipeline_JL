import { getData } from "../../../../lib/data.js";

export const dynamic = "force-dynamic";

export async function GET(_req, { params }) {
  const d = await getData();
  const issue = d.issues?.[params.id];
  if (!issue) return Response.json({ error: "issue not found" }, { status: 404 });
  // Cap member evidence returned to the client; full data stays in the DB.
  return Response.json({ issue: { ...issue, members: issue.members.slice(0, 50) } });
}
