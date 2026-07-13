import type { Metadata } from "next";
import { DocumentGroupList } from "@/features/documents/components/document-group-list";

export const metadata: Metadata = {
  title: "Document Distribution | PassDetection",
};

export default function DocumentDistributionPage() {
  return <DocumentGroupList />;
}
