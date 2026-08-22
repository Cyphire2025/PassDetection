/**
 * Dashboard Layout — Light Theme
 */
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { AuthenticatedContent } from "@/features/auth/components/authenticated-content";
import { AuthHydrator } from "@/features/auth/components/auth-hydrator";
import { WhatsAppActivityTrackerProvider } from "@/features/whatsapp/components/whatsapp-activity-tracker";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AuthHydrator />
      <AuthenticatedContent>
        <WhatsAppActivityTrackerProvider>
          <DashboardShell>{children}</DashboardShell>
        </WhatsAppActivityTrackerProvider>
      </AuthenticatedContent>
    </>
  );
}
