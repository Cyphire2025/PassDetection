import { EmailMessageActivityPage } from "@/features/email-integrations/components/message-activity-page";

export default async function EmailIntegrationMessagePage({
  params,
}: {
  params: Promise<{ messageId: string }>;
}) {
  const { messageId } = await params;
  return <EmailMessageActivityPage messageId={messageId} />;
}
