import type { Metadata } from "next";
import { DocumentWorkspace } from "@/features/documents/components/document-workspace";

export const metadata: Metadata = {
  title: "Group Documents | Global Connects Dashboard",
};

interface DocumentGroupPageProps {
  params: Promise<{ groupId: string }>;
}

export default async function DocumentGroupPage({ params }: DocumentGroupPageProps) {
  const { groupId } = await params;
  return <DocumentWorkspace groupId={groupId} />;
}
