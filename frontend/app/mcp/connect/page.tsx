import type { Metadata } from "next";
import { McpRequestWaitingPage } from "@/features/mcp/components/mcp-request-waiting-page";

export const metadata: Metadata = { title: "Connection request", referrer: "no-referrer", robots: { index: false, follow: false } };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const parameters = await searchParams;
  return <McpRequestWaitingPage requestId={parameters.request_id} />;
}
