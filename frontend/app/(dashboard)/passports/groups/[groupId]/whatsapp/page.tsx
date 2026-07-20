import type { Metadata } from "next";
import { GroupWhatsAppBroadcastTrackingPage } from "@/features/passports/components/group-whatsapp-broadcast-panel";

export const metadata: Metadata = {
  title: "WhatsApp Submission Tracking | PassDetection",
};

interface WhatsAppSubmissionTrackingPageProps {
  params: Promise<{ groupId: string }>;
}

export default async function WhatsAppSubmissionTrackingPage({
  params,
}: WhatsAppSubmissionTrackingPageProps) {
  const { groupId } = await params;
  return <GroupWhatsAppBroadcastTrackingPage groupId={groupId} />;
}
