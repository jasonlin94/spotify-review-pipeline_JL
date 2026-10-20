import { getData } from "../../../lib/data.js";

export const dynamic = "force-dynamic";

export async function GET() {
  const d = await getData();
  return Response.json({ recommendation: d.recommendation });
}
