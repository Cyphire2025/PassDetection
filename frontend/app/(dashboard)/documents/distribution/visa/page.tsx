import type { Metadata } from "next";
import { DocumentGroupList } from "@/features/documents/components/document-group-list";

export const metadata: Metadata = {
  title: "Visa Distribution Groups",
};

export default function VisaDistributionGroupsPage() {
  return <DocumentGroupList category="visa" />;
}
