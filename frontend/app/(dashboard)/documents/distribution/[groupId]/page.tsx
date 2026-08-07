import type { Metadata } from "next";
import { DocumentGroupDistributionChooser } from "@/features/documents/components/document-group-distribution-chooser";

export const metadata: Metadata = {
  title: "Group Documents",
};

interface DocumentGroupPageProps {
  params: Promise<{ groupId: string }>;
}

export default async function DocumentGroupPage({ params }: DocumentGroupPageProps) {
  const { groupId } = await params;
  return <DocumentGroupDistributionChooser groupId={groupId} />;
}
