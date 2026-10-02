import { redirect } from "next/navigation";

export default async function Page({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const parameters = await searchParams;
  redirect(typeof parameters.request_id === "string" ? `/mcp/connect?request_id=${encodeURIComponent(parameters.request_id)}` : "/mcp/connect");
}
