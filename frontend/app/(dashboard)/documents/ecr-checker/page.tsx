import type { Metadata } from "next";
import { EcrCheckerPage } from "@/features/documents/components/ecr-checker-page";

export const metadata: Metadata = { title: "ECR Checker" };

export default async function EcrPage({
  searchParams,
}: {
  searchParams: Promise<{ batch?: string | string[] }>;
}) {
  const { batch } = await searchParams;
  const batchId = typeof batch === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(batch) ? batch : null;
  return <EcrCheckerPage initialBatchId={batchId} />;
}
