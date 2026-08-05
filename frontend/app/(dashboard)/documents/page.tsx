import type { Metadata } from "next";
import { DocumentHub } from "@/features/documents/components/document-hub";

export const metadata: Metadata = {
  title: "Documents",
};

export default function DocumentsPage() {
  return <DocumentHub />;
}
