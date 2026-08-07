import type { Metadata } from "next";
import { DocumentDistributionLanding } from "@/features/documents/components/document-distribution-landing";

export const metadata: Metadata = {
  title: "Document Distribution",
};

export default function DocumentDistributionPage() {
  return <DocumentDistributionLanding />;
}
