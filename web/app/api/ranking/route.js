import { getData } from "../../../lib/data.js";

export const dynamic = "force-dynamic";

export async function GET() {
  const d = await getData();
  return Response.json({ ranking: d.ranking });
}
