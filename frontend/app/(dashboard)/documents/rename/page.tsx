import type { Metadata } from "next";
import { DocumentRenamePage } from "@/features/documents/components/document-rename-page";

export const metadata: Metadata = {
  title: "Rename Documents",
};

export default function RenameDocumentsPage() {
  return <DocumentRenamePage />;
}
