import type { Metadata } from "next";
import { McpFileTransferPage } from "@/features/mcp/components/mcp-file-transfer-page";

export const metadata: Metadata = { title: "File transfer", referrer: "no-referrer", robots: { index: false, follow: false } };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <McpFileTransferPage id={id} />;
}
