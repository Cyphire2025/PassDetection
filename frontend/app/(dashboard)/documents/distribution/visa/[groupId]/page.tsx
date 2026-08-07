import type { Metadata } from "next";
import { DocumentWorkspace } from "@/features/documents/components/document-workspace";
import { VISA_DISTRIBUTION_LANE } from "@/features/documents/config/document-distribution-lanes";

export const metadata: Metadata = {
  title: "Group Visa Documents",
};

interface VisaGroupPageProps {
  params: Promise<{ groupId: string }>;
}

export default async function VisaGroupPage({ params }: VisaGroupPageProps) {
  const { groupId } = await params;
  return (
    <DocumentWorkspace
      key={`${groupId}:${VISA_DISTRIBUTION_LANE.documentType}`}
      groupId={groupId}
      lane={VISA_DISTRIBUTION_LANE}
    />
  );
}
