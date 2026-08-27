/**
 * Dashboard Layout — Light Theme
 */
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { AuthenticatedContent } from "@/features/auth/components/authenticated-content";
import { AuthHydrator } from "@/features/auth/components/auth-hydrator";
import { RouteCapabilityBoundary } from "@/features/auth/components/route-capability-boundary";
import { DashboardRealtimeAttendanceBridge } from "@/features/operations/components/dashboard-realtime-attendance-bridge";
import { WhatsAppActivityTrackerProvider } from "@/features/whatsapp/components/whatsapp-activity-tracker";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AuthHydrator />
      <AuthenticatedContent>
        <DashboardRealtimeAttendanceBridge />
        <RouteCapabilityBoundary>
          <WhatsAppActivityTrackerProvider>
            <DashboardShell>{children}</DashboardShell>
          </WhatsAppActivityTrackerProvider>
        </RouteCapabilityBoundary>
      </AuthenticatedContent>
    </>
  );
}
