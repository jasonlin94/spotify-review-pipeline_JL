import { getData, dataSource } from "../../../lib/data.js";

export const dynamic = "force-dynamic";

export async function GET() {
  const d = await getData();
  return Response.json({
    overview: d.overview,
    generated_at: d.generated_at,
    source: dataSource(),
  });
}
