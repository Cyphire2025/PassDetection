import { McpConsentPage } from "@/features/mcp/components/mcp-consent-page";

export default async function Page({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return <McpConsentPage parameters={await searchParams} />;
}
